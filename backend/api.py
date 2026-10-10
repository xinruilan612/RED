"""FastAPI web application. Configure PUBLIC_ORIGIN and DATABASE_URL for deployment."""
import argparse
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, Request, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse, Response
from backend.auth import Auth
from backend.contracts import DomainError, require
from backend.provider import Config, load_config
from backend.service import Service
from backend.store import Store
from backend.web import FRONTEND, view


def settings():
    values = {}
    path = Path(__file__).resolve().parents[1]/'.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.strip().startswith('#'):
                k,v=line.split('=',1); values[k.strip()]=v.strip().strip('\"\'')
    return {**values, **os.environ}


def create_app(store=None, config=None, origin=None, invite=None, client=None):
    env = settings()
    origin = (origin or env.get('PUBLIC_ORIGIN','http://127.0.0.1:8765')).rstrip('/')
    parsed = urlsplit(origin)
    require(parsed.scheme in ('http','https') and parsed.netloc and parsed.path in ('','/') and not parsed.query and not parsed.fragment and not parsed.username, 'CONFIG_INVALID','PUBLIC_ORIGIN 格式无效')
    local = parsed.hostname in ('127.0.0.1','localhost','testserver')
    invite = env.get('REGISTRATION_INVITE','') if invite is None else invite
    require(local or (parsed.scheme=='https' and len(invite)>=16), 'CONFIG_INVALID','公网运行需 HTTPS 和至少16位注册邀请码')
    if not local:
        master_key = env.get('MODEL_CREDENTIAL_KEY','').strip()
        require(master_key, 'CONFIG_INVALID','公网运行必须显式配置 MODEL_CREDENTIAL_KEY 加密主密钥')
        from cryptography.fernet import Fernet
        try:
            Fernet(master_key.encode())
        except (ValueError,TypeError):
            raise DomainError('CONFIG_INVALID','MODEL_CREDENTIAL_KEY 格式无效；需要 Fernet 主密钥') from None
    store = store or Store(env.get('DATABASE_URL','runtime/web.sqlite'))
    config = config if config is not None else load_config()
    auth, service = Auth(store), Service(store,config,client,allow_windtunnel_live=env.get('WINDTUNNEL_ALLOW_LIVE','').lower()=='true')
    app = FastAPI(title='有迹运营 API', version='0.7.0', docs_url=None, redoc_url=None)
    app.state.store,app.state.service,app.state.auth = store,service,auth

    def failure(error):
        code = {'RESOURCE_NOT_FOUND':404,'AUTH_REQUIRED':401,'FORBIDDEN':403,'INVALID_INPUT':400,'RATE_LIMITED':429}.get(error.code,409)
        return JSONResponse({'error':{'code':error.code,'message':str(error)}},status_code=code)

    @app.exception_handler(DomainError)
    async def domain_error(request, error): return failure(error)

    @app.exception_handler(RequestValidationError)
    async def input_error(request, error): return failure(DomainError('INVALID_INPUT','请求格式无效'))

    @app.exception_handler(Exception)
    async def unexpected(request, error):
        # Never expose provider responses, SQL connection strings or user content.
        import logging
        logging.getLogger('youji').error('request failed: %s',type(error).__name__)
        return JSONResponse({'error':{'code':'INTERNAL_ERROR','message':'操作失败，原记录已保留，请稍后重试'}},status_code=500)

    @app.middleware('http')
    async def protect(request, call_next):
        try:
            require(request.headers.get('host')==parsed.netloc, 'FORBIDDEN','请求地址与网站配置不符')
            if request.method not in ('GET','HEAD','OPTIONS'):
                require(request.headers.get('origin')==origin, 'FORBIDDEN','仅允许本站发起操作')
                session = auth.session(request.cookies.get('youji_session',''))
                require(session and secrets.compare_digest(request.headers.get('x-csrf-token',''),session['csrf']), 'FORBIDDEN','页面会话已过期，请刷新')
                require(request.headers.get('content-type','').split(';')[0]=='application/json','INVALID_INPUT','只接受 JSON')
                chunks=[]; size=0
                async for chunk in request.stream():
                    size+=len(chunk)
                    require(size<=8_000_000,'INVALID_INPUT','请求超过 8 MB')
                    chunks.append(chunk)
                request._body=b''.join(chunks)
            response=await call_next(request)
        except DomainError as error:
            response=failure(error)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'same-origin',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    def logged(request: Request):
        session=auth.session(request.cookies.get('youji_session',''))
        require(session and session['user'],'AUTH_REQUIRED','请先登录网站')
        return session

    def set_cookie(response, token):
        response.set_cookie('youji_session',token,httponly=True,secure=parsed.scheme=='https',samesite='strict',max_age=604800,path='/')
        return response

    @app.get('/health')
    def health():
        with store.connect() as db: db.execute('SELECT 1')
        return {'status':'ok','database':'postgresql' if store.postgres else 'sqlite','version':'0.7.0'}

    @app.get('/api/session')
    def session(request: Request):
        token=request.cookies.get('youji_session','')
        current=auth.session(token)
        if not current:
            auth.throttle('session:'+request.client.host,100,60)
            token=auth.issue(previous=token); current=auth.session(token)
        provider=service.models.effective_public(current['owner']) if current['user'] else config.public()
        response=JSONResponse({'csrf':current['csrf'],'user':current['user'],'auth_required':True,'invite_required':bool(invite),'provider':provider})
        return set_cookie(response,token)

    @app.post('/api/auth/{action}')
    def authenticate(action: str, data: dict, request: Request):
        token=request.cookies.get('youji_session','')
        if action=='logout':
            auth.logout(token)
            response=JSONResponse({'ok':True});response.delete_cookie('youji_session',path='/');return response
        require(action in ('register','login','reset'),'RESOURCE_NOT_FOUND','操作不存在')
        auth.throttle('auth-ip:'+request.client.host,30)
        auth.throttle('auth-name:'+str(data.get('username','')).lower(),12)
        recovery=None
        if action=='register': identity,recovery=auth.register(data,request.cookies.get('xhs_demo',''),invite)
        elif action=='reset': identity,recovery=auth.reset(data)
        else: identity=auth.login(data)
        fresh=auth.issue(identity,token)
        current=auth.session(fresh)
        return set_cookie(JSONResponse({'user':current['user'],'csrf':current['csrf'],'recovery_code':recovery}),fresh)

    @app.get('/api/operations')
    def operations(user=Depends(logged)): return service.operations.read(user['owner'])

    @app.get('/api/models')
    def models(user=Depends(logged)): return service.models.public(user['owner'])

    @app.post('/api/models/connections')
    def save_model(data: dict,user=Depends(logged)):
        auth.throttle('model-settings:'+user['owner'],30,3600)
        return service.models.save(user['owner'],data)

    @app.post('/api/models/default')
    def default_model(data: dict,user=Depends(logged)):
        return service.models.select(user['owner'],data)

    @app.post('/api/models/connections/{connection_id}/delete')
    def delete_model(connection_id: str,data: dict,user=Depends(logged)):
        return service.models.delete(user['owner'],connection_id,data)

    @app.post('/api/models/connections/{connection_id}/test')
    def test_model(connection_id: str,data: dict,user=Depends(logged)):
        auth.throttle('model-test:'+user['owner'],6,3600)
        return service.models.test(user['owner'],connection_id,data)

    @app.get('/api/social/connection')
    def social_connection(account_id: str,user=Depends(logged)):
        from backend.social_connections import SocialConnections
        return SocialConnections(service.operations).read(user['owner'],account_id)

    @app.get('/api/social/sync')
    def social_sync(account_id: str,user=Depends(logged)):
        from backend.xhs_sync import XHSSync
        return XHSSync(store).public(user['owner'],account_id)

    @app.get('/api/social/sync/notes')
    def social_sync_notes(account_id: str,user=Depends(logged)):
        from backend.xhs_sync import XHSSync
        return XHSSync(store).records(user['owner'],account_id)

    @app.get('/api/social/sync/comments')
    def social_sync_comments(account_id: str,note_id: str,offset: int=0,user=Depends(logged)):
        from backend.xhs_sync import XHSSync
        return XHSSync(store).comments(user['owner'],account_id,note_id,offset)

    @app.post('/api/social/sync/import-case')
    def import_social_sync_case(data: dict,user=Depends(logged)):
        from backend.xhs_case_import import XHSCaseImport
        auth.throttle('xhs-import-case:'+user['owner'],40,3600)
        result=XHSCaseImport(store).save(user['owner'],data)
        result.pop('versions',None)
        return result

    @app.post('/api/social/sync/control')
    def control_social_sync(data: dict,user=Depends(logged)):
        from backend.xhs_sync import XHSSync
        require(set(data)=={'account_id','action'},'INVALID_INPUT','同步操作字段无效')
        auth.throttle('xhs-control:'+user['owner'],20,3600)
        return XHSSync(store).control(user['owner'],data['account_id'],data['action'])

    @app.get('/api/search/settings')
    def search_settings(user=Depends(logged)):
        from backend.search_providers import SearchSettings
        return SearchSettings(store).public(user['owner'])

    @app.post('/api/search/settings')
    def save_search_settings(data: dict,user=Depends(logged)):
        from backend.search_providers import SearchSettings
        auth.throttle('search-settings:'+user['owner'],30,3600)
        return SearchSettings(store).save(user['owner'],data)

    @app.get('/api/research/cases')
    def cases(account_id: str,user=Depends(logged)):
        from backend.research_cases import ResearchCases
        return ResearchCases(store).list(user['owner'],account_id)

    @app.post('/api/research/cases')
    def save_case(data: dict,user=Depends(logged)):
        from backend.research_cases import ResearchCases
        auth.throttle('case-save:'+user['owner'],40,3600)
        result=ResearchCases(store).save(user['owner'],data)
        result.pop('original_base64',None)
        result.pop('versions',None)
        return result

    @app.post('/api/research/cases/import-url')
    def import_case(data: dict,user=Depends(logged)):
        from backend.research_cases import ResearchCases
        from backend.sources import read_article
        require(set(data)=={'account_id','url','evidence_role','permission_confirmed'},'INVALID_INPUT','案例导入字段无效')
        service.knowledge.account(user['owner'],data['account_id'])
        require(data['permission_confirmed'] is True,'INVALID_INPUT','请确认有权将这份资料用于本项目研究')
        # The source is checked before a network request, not after collection.
        from backend.research_access import require_readable_source
        require_readable_source(data['url'])
        auth.throttle('case-import:'+user['owner'],20,3600)
        article=read_article(data['url'])
        result=ResearchCases(store).from_article(user['owner'],data['account_id'],article,
                 evidence_role=data['evidence_role'],permission_confirmed=True)
        result.pop('original_base64',None)
        result.pop('versions',None)
        return result

    @app.get('/api/research/cases/export')
    def export_cases(account_id: str,user=Depends(logged)):
        from backend.research_cases import ResearchCases
        result=ResearchCases(store).export(user['owner'],account_id)
        return Response(result['content'],media_type='text/markdown',headers={'Content-Disposition':'attachment; filename="youji-case-research.md"'})

    @app.get('/api/research/jobs')
    def research_jobs(account_id: str,user=Depends(logged)):
        from backend.research_jobs import ResearchJobs
        return ResearchJobs(store).list(user['owner'],account_id)

    @app.post('/api/research/jobs',status_code=202)
    def start_research(data: dict,user=Depends(logged)):
        from backend.research_jobs import ResearchJobs
        auth.throttle('research-job:'+user['owner'],10,3600)
        return ResearchJobs(store).create(user['owner'],data)

    @app.get('/api/research/jobs/{job_id}')
    def get_research(job_id: str,user=Depends(logged)):
        from backend.research_jobs import ResearchJobs
        return ResearchJobs(store).get(user['owner'],job_id)

    @app.post('/api/research/jobs/{job_id}/cancel')
    def cancel_research(job_id: str,data: dict,user=Depends(logged)):
        from backend.research_jobs import ResearchJobs
        require(not data,'INVALID_INPUT','取消操作无需额外参数')
        return ResearchJobs(store).cancel(user['owner'],job_id)

    @app.get('/api/research/jobs/{job_id}/export')
    def export_research(job_id: str,user=Depends(logged)):
        from backend.research_jobs import ResearchJobs
        result=ResearchJobs(store).export(user['owner'],job_id)
        return Response(result['content'],media_type='text/markdown',headers={'Content-Disposition':'attachment; filename="youji-research-report.md"'})

    @app.get('/api/knowledge')
    def documents(account_id: str,user=Depends(logged)): return service.knowledge.list(user['owner'],account_id)

    @app.post('/api/knowledge')
    def save_document(data: dict,user=Depends(logged)):
        auth.throttle('upload:'+user['owner'],40,3600)
        try:
            result=service.knowledge.save(user['owner'],data)
            result.pop('chunks',None);result.pop('versions',None)
            return result
        except DomainError: raise
        except ValueError as e: raise DomainError('INVALID_INPUT',str(e)) from None

    @app.get('/api/knowledge/{document_id}')
    def document(document_id: str,account_id: str,user=Depends(logged)):
        return service.knowledge.get(user['owner'],account_id,document_id)

    @app.post('/api/knowledge/{document_id}/delete')
    def delete_document(document_id: str,data: dict,user=Depends(logged)):
        require(set(data)=={'account_id','version'},'INVALID_INPUT','删除字段无效')
        return service.knowledge.delete(user['owner'],data['account_id'],document_id,data['version'])

    @app.post('/api/knowledge/retrieve')
    def retrieve(data: dict,user=Depends(logged)):
        require(set(data)=={'account_id','query'},'INVALID_INPUT','检索字段无效')
        return service.knowledge.retrieve(user['owner'],data['account_id'],data['query'])

    @app.post('/api/sources/search')
    def search(data: dict,user=Depends(logged)):
        from backend.search_providers import SearchSettings
        require({'query','account_id'}<=set(data)<={'query','account_id','provider','targets'},'INVALID_INPUT','搜索字段无效')
        service.knowledge.account(user['owner'],data['account_id'])
        auth.throttle('search:'+user['owner'],30,3600)
        return SearchSettings(store).search(user['owner'],data['query'],provider=data.get('provider','bing'),targets=data.get('targets'))

    @app.post('/api/sources/import')
    def import_source(data: dict,user=Depends(logged)):
        from backend.sources import read_article
        require(set(data)=={'url','account_id'},'INVALID_INPUT','来源字段无效')
        service.knowledge.account(user['owner'],data['account_id'])
        from backend.research_access import require_readable_source
        require_readable_source(data['url'])
        auth.throttle('fetch:'+user['owner'],30,3600)
        article=read_article(data['url'])
        return service.knowledge.save(user['owner'],{'account_id':data['account_id'],'title':article['title'],'text':article['text']},
                                      source_type='web',source_url=article['url'],metadata={k:article[k] for k in ('fetched_at','published_at','verification')})

    @app.post('/api/operations')
    def operate(data: dict, user=Depends(logged)): return service.operations.command(user['owner'],data)

    @app.post('/api/operations/agent-plan')
    def agent_plan(data: dict, user=Depends(logged)):
        auth.throttle('operations-plan:'+user['owner'],12,3600)
        return service.operations_planner.generate(user['owner'],data)

    @app.get('/api/operations/due')
    def due(user=Depends(logged)):
        from backend.planning import due_reviews
        return due_reviews(service.operations.read(user['owner']))

    @app.get('/api/runs')
    def runs(user=Depends(logged)): return [service.view(r) for r in store.list_runs(user['owner'])]

    @app.get('/api/windtunnel/checklists')
    def windtunnel_checklists(account_id: str,user=Depends(logged)):
        return service.windtunnel.checklists(user['owner'],account_id)

    @app.post('/api/windtunnel/checklists')
    def save_windtunnel_checklist(data: dict,user=Depends(logged)):
        return service.windtunnel.save_checklist(user['owner'],data)

    @app.post('/api/runs',status_code=201)
    def create(data: dict, user=Depends(logged)): return service.create(user['owner'],data)

    @app.get('/api/runs/{run_id}')
    def get_run(run_id: str,user=Depends(logged)): return service.view(store.get(run_id,user['owner']))

    @app.post('/api/runs/{run_id}/actions')
    def act(run_id: str,data: dict,user=Depends(logged)): return service.action(user['owner'],run_id,data)

    @app.post('/api/runs/{run_id}/background',status_code=202)
    def background(run_id: str,data: dict,user=Depends(logged)):
        return service.background(user['owner'],run_id,data)

    @app.get('/api/runs/{run_id}/export')
    def export(run_id: str,user=Depends(logged)):
        return Response(service.export(user['owner'],run_id),media_type='text/markdown',headers={'Content-Disposition':'attachment; filename="youji-draft.md"'})

    @app.get('/')
    def index(): return FileResponse(FRONTEND/'index.html', media_type='text/html')

    @app.get('/{asset}')
    def asset(asset: str):
        require(asset in ('style.css','app.js','operations.js','account.js','account_profile.js','auth.js','knowledge.js','windtunnel.js','windtunnel.css','trials.js','trials.css','connections.js','research.js'),'RESOURCE_NOT_FOUND','页面不存在')
        require((FRONTEND/asset).is_file(),'RESOURCE_NOT_FOUND','页面不存在')
        # Do not inherit OS/Windows registry MIME associations: nosniff browsers
        # refuse JavaScript served as text/plain even when the file is valid.
        return FileResponse(FRONTEND/asset, media_type='text/javascript' if asset.endswith('.js') else 'text/css')

    return app


def main():
    import uvicorn
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--host',default='127.0.0.1')
    args=parser.parse_args()
    uvicorn.run(create_app(),host=args.host,port=args.port,access_log=False)


if __name__=='__main__': main()

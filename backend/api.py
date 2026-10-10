"""FastAPI web application. Configure PUBLIC_ORIGIN and DATABASE_URL for deployment."""
import argparse
import json
import os
import re
import secrets
from threading import BoundedSemaphore
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, Request, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse, Response
from backend.auth import Auth
from backend.public_topics import public_response
from backend.contracts import DomainError, require
from backend.provider import Config, load_config
from backend.service import Service
from backend.store import Store
from backend.web import FRONTEND, view


def settings():
    values = {}
    path = Path(__file__).resolve().parents[1]/'.env'
    if os.environ.get('YOUJI_IGNORE_PROJECT_ENV') != '1' and path.exists():
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
    store = store or Store(env.get('DATABASE_URL','runtime/web.sqlite'))
    config = config if config is not None else load_config()
    auth, service = Auth(store), Service(store,config,client,allow_windtunnel_live=env.get('WINDTUNNEL_ALLOW_LIVE','').lower()=='true')
    app = FastAPI(title='有迹运营 API', version='0.7.0', docs_url=None, redoc_url=None)
    app.state.store,app.state.service,app.state.auth = store,service,auth
    media_slots = BoundedSemaphore(2)

    @contextmanager
    def media_slot():
        require(media_slots.acquire(blocking=False), 'RATE_LIMITED', '图卡正在制作，请稍后重试')
        try: yield
        finally: media_slots.release()

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
                limit=15_000_000 if re.fullmatch(r"/api/runs/[^/]+/poster(?:/generate)?",request.url.path) else 8_000_000
                chunks=[]; size=0
                async for chunk in request.stream():
                    size+=len(chunk)
                    require(size<=limit,'INVALID_INPUT',f'请求超过 {limit//1_000_000} MB')
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
        response=JSONResponse({'csrf':current['csrf'],'user':current['user'],'auth_required':True,'invite_required':bool(invite),'provider':config.public()})
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

    from backend.topics import Topics
    topics = Topics(service.operations)
    app.state.topics = topics

    @app.get('/api/topics')
    def topic_settings(account_id: str, user=Depends(logged)):
        return topics.read(user['owner'], account_id)

    from backend.public_topics import PublicTopics
    public_topics = PublicTopics(service.operations)
    app.state.public_topics = public_topics

    @app.get('/api/topics/public')
    def public_topic_samples(account_id: str, user=Depends(logged)):
        return public_topics.read(user['owner'],account_id)

    @app.post('/api/topics/public/{action}')
    def public_topic_action(action: str, data: dict, user=Depends(logged)):
        actions={'search':public_topics.search,'refresh':public_topics.refresh,
                 'remove':public_topics.remove,'import':public_topics.import_samples,'connect':public_topics.connect}
        require(action in actions,'RESOURCE_NOT_FOUND','操作不存在')
        auth.throttle('public-topics:'+user['owner'],30,3600)
        return actions[action](user['owner'],data)

    @app.post('/api/topics/{action}')
    def topic_action(action: str, data: dict, user=Depends(logged)):
        require(action in ('config','history-image','evaluate','training-data'),'RESOURCE_NOT_FOUND','操作不存在')
        auth.throttle('topics:'+user['owner'],30,3600)
        from backend.topic_encoder import TopicEncoderError
        try:
            return {'config':topics.save,'history-image':topics.image,'evaluate':topics.evaluate,'training-data':topics.training_data}[action](user['owner'],data)
        except DomainError:
            raise
        except TopicEncoderError as error:
            raise DomainError('TOPIC_MODEL_UNAVAILABLE',str(error)) from None
        except ValueError:
            raise DomainError('INVALID_INPUT','图文或选题设置无效，请检查后重试') from None

    @app.get('/api/skapp/report')
    def skapp_report(user=Depends(logged)):
        from backend.skapp_report import read_report
        return read_report()

    @app.get('/api/skapp/report/download')
    def skapp_report_download(user=Depends(logged)):
        from backend.skapp_report import read_report
        report = read_report()
        require(report['status'] == 'ready', 'RESOURCE_NOT_FOUND', '暂时没有可下载的实验报告')
        return Response(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2),
                        media_type='application/json', headers={'Content-Disposition': 'attachment; filename=youji-skapp-report.json'})

    @app.get('/api/operations')
    def operations(user=Depends(logged)): return public_response(service.operations.read(user['owner']))

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
        from backend.sources import search_web
        require({'query','account_id'}<=set(data)<={'query','account_id','provider'},'INVALID_INPUT','搜索字段无效')
        service.knowledge.account(user['owner'],data['account_id'])
        auth.throttle('search:'+user['owner'],30,3600)
        return search_web(data['query'],provider=data.get('provider','bing'))

    @app.post('/api/sources/import')
    def import_source(data: dict,user=Depends(logged)):
        from backend.sources import read_article
        require(set(data)=={'url','account_id'},'INVALID_INPUT','来源字段无效')
        service.knowledge.account(user['owner'],data['account_id'])
        auth.throttle('fetch:'+user['owner'],30,3600)
        article=read_article(data['url'])
        return service.knowledge.save(user['owner'],{'account_id':data['account_id'],'title':article['title'],'text':article['text']},
                                      source_type='web',source_url=article['url'],metadata={k:article[k] for k in ('fetched_at','published_at','verification')})

    @app.post('/api/operations')
    def operate(data: dict, user=Depends(logged)): return public_response(service.operations.command(user['owner'],data))

    @app.post('/api/operations/agent-plan')
    def agent_plan(data: dict, user=Depends(logged)):
        auth.throttle('operations-plan:'+user['owner'],12,3600)
        return public_response(service.operations_planner.generate(user['owner'],data))

    @app.post('/api/operations/ai-review')
    def ai_review(data: dict,user=Depends(logged)):
        auth.throttle('ai-review:'+user['owner'],12,3600)
        return public_response(service.analytics_review.generate(user['owner'],data))

    @app.get('/api/operations/due')
    def due(user=Depends(logged)):
        from backend.planning import due_reviews
        return due_reviews(service.operations.read(user['owner']))

    @app.get('/api/runs')
    def runs(deleted: bool=False,user=Depends(logged)): return [service.view(r) for r in store.list_runs(user['owner'],deleted=deleted)]

    @app.post('/api/runs/{run_id}/visibility')
    def visibility(run_id: str,data: dict,user=Depends(logged)):
        require(set(data)=={'deleted'},'INVALID_INPUT','删除字段无效')
        return store.set_visibility(run_id,user['owner'],data['deleted'])

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

    @app.post('/api/runs/{run_id}/return-to-creation')
    def return_to_creation(run_id: str,data: dict,user=Depends(logged)):
        return service.return_to_creation(user['owner'],run_id,data)

    @app.post('/api/runs/{run_id}/background',status_code=202)
    def background(run_id: str,data: dict,user=Depends(logged)):
        return service.background(user['owner'],run_id,data)

    @app.get('/api/runs/{run_id}/export')
    def export(run_id: str,user=Depends(logged)):
        body = service.export(user['owner'], run_id)
        run = store.get(run_id, user['owner'])
        filename = 'youji-reader-check-' + run.run_id[:8] + '.md' if run.workflow_type == 'windtunnel' else 'youji-draft.md'
        return Response(body, media_type='text/markdown', headers={'Content-Disposition': f'attachment; filename="{filename}"'})

    @app.get('/')
    def index(): return FileResponse(FRONTEND/'index.html')

    @app.get('/api/media/templates')
    def media_templates(run_id: str=None,user=Depends(logged)):
        from backend.media_templates import catalog
        return catalog(store,user['owner'],run_id)

    @app.post('/api/runs/{run_id}/media/template-next')
    def media_template_next(run_id: str,data: dict,user=Depends(logged)):
        from backend.media_templates import choose
        return choose(store,user['owner'],run_id,data)

    @app.get('/assets/templates/{filename}')
    def media_template_thumbnail(filename: str):
        from backend.media_templates import TEMPLATE_IDS
        require(filename in {identity+'.png' for identity in TEMPLATE_IDS},'RESOURCE_NOT_FOUND','模板预览不存在')
        path=FRONTEND/'assets'/'templates'/filename
        require(path.is_file(),'RESOURCE_NOT_FOUND','模板预览不存在')
        return FileResponse(path,media_type='image/png')

    @app.get('/api/runs/{run_id}/media/capabilities')
    def media_capabilities(run_id: str,user=Depends(logged)):
        store.get(run_id,user['owner'])
        from backend.media_exports import capabilities
        return capabilities()

    def media_target(run_id, data, user, exporting=False):
        fields={'template','options','draft_ref','content_hash'} | ({'kind','design_hash'} if exporting else set())
        require(isinstance(data,dict) and set(data)<=fields, 'INVALID_INPUT', '图卡请求字段无效')
        run=store.get(run_id,user['owner'])
        from backend.media_exports import confirmed_snapshot
        snapshot=confirmed_snapshot(run)
        require(data.get('draft_ref')==snapshot['draft_ref'] and data.get('content_hash')==snapshot['content_hash'],
                'VERSION_CONFLICT', '稿件版本已变化，请重新打开预览')
        if exporting:
            require(isinstance(data.get('design_hash'),str) and len(data['design_hash'])==64,
                    'INVALID_INPUT', '请先预览当前样式，再下载成品')
        return run

    @app.get('/api/runs/{run_id}/poster')
    def poster_read(run_id: str,user=Depends(logged)):
        from backend.posters import read
        with media_slot(): return read(store,user['owner'],run_id)

    @app.post('/api/runs/{run_id}/poster')
    def poster_mutate(run_id: str,data: dict,user=Depends(logged)):
        from backend.posters import mutate
        auth.throttle('poster:'+user['owner'],60,3600)
        with media_slot(): return mutate(store,user['owner'],run_id,data)

    @app.post('/api/runs/{run_id}/poster/generate')
    def poster_generate(run_id: str,data: dict,user=Depends(logged)):
        from backend.posters import generate
        auth.throttle('poster-generate:'+user['owner'],30,3600)
        with media_slot(): return generate(store,user['owner'],run_id,data)

    @app.post('/api/runs/{run_id}/poster/export')
    def poster_export(run_id: str,data: dict,user=Depends(logged)):
        from backend.posters import export
        with media_slot(): body,media_type,filename=export(store,user['owner'],run_id,data)
        return Response(body,media_type=media_type,headers={'Content-Disposition':'attachment; filename='+filename})

    @app.get('/api/runs/{run_id}/studio')
    def studio_read(run_id: str,user=Depends(logged)):
        from backend.studio import read
        with media_slot(): return read(store,user['owner'],run_id)

    @app.post('/api/runs/{run_id}/studio')
    def studio_mutate(run_id: str,data: dict,user=Depends(logged)):
        from backend.studio import mutate
        auth.throttle('studio:'+user['owner'],120,3600)
        with media_slot(): return mutate(store,user['owner'],run_id,data)

    @app.post('/api/runs/{run_id}/studio/export')
    def studio_export(run_id: str,data: dict,user=Depends(logged)):
        from backend.studio import export
        auth.throttle('studio-export:'+user['owner'],20,3600)
        run=store.get(run_id,user['owner'])
        with media_slot():
            body,media_type,filename=export(store,user['owner'],run_id,data,execution=service.view(run) if data.get('kind')=='complete' else None)
        return Response(body,media_type=media_type,headers={'Content-Disposition':'attachment; filename='+filename})

    @app.post('/api/runs/{run_id}/media-preview')
    def media_preview(run_id: str,data: dict,user=Depends(logged)):
        run=media_target(run_id,data,user)
        auth.throttle('media-preview:'+user['owner'],120,3600)
        from backend.media_exports import preview_run
        with media_slot():
            return preview_run(run,template=data.get('template','classic'),options=data.get('options'))

    @app.post('/api/runs/{run_id}/media-adjust-preview')
    def media_adjust_preview(run_id: str,data: dict,user=Depends(logged)):
        require(isinstance(data,dict) and set(data)<={'template','options','draft_ref','content_hash','design_hash','page_index','feedback'},'INVALID_INPUT','图卡调整请求字段无效')
        from backend.html_cards import THEMES
        require(data.get('template') in THEMES,'INVALID_INPUT','请先选择当前模板库中的图卡')
        target={key:data[key] for key in ('template','options','draft_ref','content_hash') if key in data}
        run=media_target(run_id,target,user)
        require(type(data.get('page_index')) is int and 0<=data['page_index']<24,'INVALID_INPUT','请选择一张图卡')
        require(isinstance(data.get('feedback'),str) and 1<=len(data['feedback'].strip())<=1000,'INVALID_INPUT','请填写1至1000字修改意见')
        auth.throttle('media-adjust:'+user['owner'],20,3600)
        from backend.media_exports import preview_run
        from backend.media_adjust import propose
        from backend.model_router import Calls
        with media_slot():
            before=preview_run(run,template=data.get('template','classic'),options=data.get('options'))
        require(data.get('design_hash')==before['design_hash'],'VERSION_CONFLICT','图片已变化，请重新预览后调整')
        require(data['page_index']<len(before['pages']),'INVALID_INPUT','所选图卡不存在')
        selected=before['pages'][data['page_index']]
        result=Calls.invoke_local_vision(store,run,selected['data_url'],data['feedback'].strip(),selected.get('text_blocks',[]))
        # The caller may have changed the confirmed draft while local inference was running.
        current=media_target(run_id,target,user)
        with media_slot():
            return propose(current,data,before,result)

    @app.post('/api/runs/{run_id}/media-export')
    def media_export_design(run_id: str,data: dict,user=Depends(logged)):
        run=media_target(run_id,data,user,exporting=True)
        auth.throttle('media-export:'+user['owner'],20,3600)
        from backend.media_exports import export_run
        kind=data.get('kind','complete')
        with media_slot():
            body,media_type,filename=export_run(run,kind,execution=service.view(run) if kind=='complete' else None,
                template=data.get('template','classic'),options=data.get('options'),expected_design_hash=data['design_hash'])
        return Response(body,media_type=media_type,headers={'Content-Disposition':'attachment; filename='+filename})

    @app.get('/api/runs/{run_id}/media-export')
    def media_export(run_id: str,kind: str='images',template: str='classic',user=Depends(logged)):
        auth.throttle('media-export:'+user['owner'],20,3600)
        from backend.media_exports import export_run
        run=store.get(run_id,user['owner'])
        with media_slot():
            body,media_type,filename=export_run(run,kind,execution=service.view(run) if kind=='complete' else None,template=template)
        return Response(body,media_type=media_type,headers={'Content-Disposition': 'attachment; filename='+filename})

    @app.get('/{asset}')
    def asset(asset: str):
        require(asset in ('style.css','app.js','operations.js','account.js','account_profile.js','auth.js','knowledge.js','windtunnel.js','windtunnel.css','trials.js','trials.css','guidance.js','media_exports.js','media_exports.css','posters.js','posters.css','poster_generation.js','skapp.js','topics.js','topics.css'),'RESOURCE_NOT_FOUND','页面不存在')
        require((FRONTEND/asset).is_file(),'RESOURCE_NOT_FOUND','页面不存在')
        media_type = 'text/css' if asset.endswith('.css') else 'text/javascript'
        return FileResponse(FRONTEND/asset, media_type=media_type)

    return app


def main():
    import uvicorn
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--host',default='127.0.0.1')
    args=parser.parse_args()
    uvicorn.run(create_app(),host=args.host,port=args.port,access_log=False)


if __name__=='__main__': main()

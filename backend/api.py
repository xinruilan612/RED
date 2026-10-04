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

    @app.get('/api/operations')
    def operations(user=Depends(logged)): return service.operations.read(user['owner'])

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
    def index(): return FileResponse(FRONTEND/'index.html')

    @app.get('/{asset}')
    def asset(asset: str):
        require(asset in ('style.css','app.js','operations.js','account.js','account_profile.js','auth.js','knowledge.js','windtunnel.js','windtunnel.css','trials.js','trials.css','guidance.js'),'RESOURCE_NOT_FOUND','页面不存在')
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

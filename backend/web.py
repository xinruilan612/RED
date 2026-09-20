"""Loopback-only demo adapter. Production authentication/deployment are not provided."""
import argparse
import hashlib
import json
import secrets
from dataclasses import asdict
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from backend.contracts import DomainError, require, integer
from backend.demo import actions, validate_brief, validate_edit
from backend.store import Store

FRONTEND = Path(__file__).resolve().parents[1]/'frontend'


def view(run):
    result=asdict(run)
    result.pop('owner_id')
    result['allowed_actions']=actions(run)
    result['mode']='simulation'
    result['usage']={'model_calls':0,'tokens':0,'cost':0,'currency':'CNY'}
    return result


class DemoServer(ThreadingHTTPServer):
    daemon_threads=True

    def __init__(self, address, store):
        self.store=store
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS demo_sessions (token_hash TEXT PRIMARY KEY, owner TEXT NOT NULL, csrf TEXT NOT NULL)')
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version='XHS-Demo/0.1'

    def send(self, status, value, content_type='application/json; charset=utf-8', cookie=None, filename=None):
        body=json.dumps(value,ensure_ascii=False).encode() if not isinstance(value,bytes) else value
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','same-origin')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie: self.send_header('Set-Cookie',cookie)
        if filename: self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.end_headers(); self.wfile.write(body)

    def host(self):
        host=self.headers.get('Host','')
        require(host in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'),
                'FORBIDDEN','只允许本机同源访问')
        return 'http://'+host

    def session(self, create=False):
        cookies=SimpleCookie()
        try: cookies.load(self.headers.get('Cookie',''))
        except Exception: pass
        token=cookies['xhs_demo'].value if 'xhs_demo' in cookies else ''
        key=hashlib.sha256(token.encode()).hexdigest()
        with self.server.store.connect() as db:
            row=db.execute('SELECT owner,csrf FROM demo_sessions WHERE token_hash=?',(key,)).fetchone() if token else None
            if row: return row[0],row[1],None
            require(create,'AUTH_REQUIRED','请刷新网页以恢复本地会话')
            token=secrets.token_urlsafe(32); owner=str(uuid4()); csrf=secrets.token_urlsafe(32)
            db.execute('INSERT INTO demo_sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),owner,csrf))
        return owner,csrf,f'xhs_demo={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800'

    def do_GET(self): self.dispatch(False)
    def do_POST(self): self.dispatch(True)

    def dispatch(self, write):
        try:
            origin=self.host(); path=urlsplit(self.path).path
            if not write and path in ('/','/app.js','/style.css'):
                name={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[path]
                mime={'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}[path]
                self.send(200,(FRONTEND/name).read_bytes(),mime); return
            if not write and path=='/api/session':
                _,csrf,cookie=self.session(True)
                self.send(200,{'csrf':csrf,'mode':'simulation'},cookie=cookie); return
            owner,csrf,_=self.session()
            if write:
                require(self.headers.get('Origin')==origin and secrets.compare_digest(self.headers.get('X-CSRF-Token',''),csrf),
                        'FORBIDDEN','页面已失效或请求不是同源，请刷新')
                require(self.headers.get('Content-Type','').split(';')[0]=='application/json','INVALID_INPUT','只接受 JSON')
                try: size=int(self.headers.get('Content-Length','0'))
                except ValueError: size=-1
                require(0<size<=40000,'INVALID_INPUT','请求大小超限')
                try: data=json.loads(self.rfile.read(size))
                except (ValueError,UnicodeDecodeError): raise DomainError('INVALID_INPUT','JSON 无效')
                require(isinstance(data,dict),'INVALID_INPUT','请求须为对象')
            if path=='/api/runs':
                if write:
                    context=validate_brief(data)
                    run=self.server.store.create(owner,str(uuid4()),context)
                    self.send(201,view(run))
                else: self.send(200,[view(r) for r in self.server.store.list_runs(owner)])
                return
            parts=path.strip('/').split('/')
            require(len(parts) in (3,4) and parts[:2]==['api','runs'],'RESOURCE_NOT_FOUND','页面不存在')
            run_id=parts[2]; run=self.server.store.get(run_id,owner)
            if not write:
                if len(parts)==3: self.send(200,view(run)); return
                require(parts[3]=='export' and 'export' in actions(run),'INVALID_TRANSITION','确认稿件后才能导出')
                draft=run.drafts[-1]['content']
                body='# 模拟创作稿（未调用真实 AI）\n\n# '+draft['selected_title']+'\n\n'+draft['body']+'\n\n'+draft['cta']+'\n\n'+' '.join('#'+t for t in draft['tags'])
                self.send(200,body.encode(),'text/markdown; charset=utf-8',filename='xhs-demo.md'); return
            require(len(parts)==4 and parts[3]=='actions','RESOURCE_NOT_FOUND','操作不存在')
            require(set(data)=={'action','version','key','payload'},'INVALID_INPUT','命令字段无效')
            action=data['action']; payload=data['payload']
            require(isinstance(action,str) and action in ('next','edit','supplement','accept','cancel'),'INVALID_TRANSITION','当前不能执行这个操作')
            integer(data['version'],'version')
            require(isinstance(data['key'],str) and 0<len(data['key'])<=100,'INVALID_INPUT','操作标识无效')
            require(isinstance(payload,dict),'INVALID_INPUT','操作参数无效')
            if action=='next':
                require(not payload,'INVALID_INPUT','下一步不能带额外参数'); command='demo_step'
            elif action=='edit': command='edit'; payload={'content':validate_edit(payload)}
            elif action=='supplement':
                require(set(payload)=={'material','allow_hypothesis'},'INVALID_INPUT','补料字段无效'); command='demo_supplement'
            elif action=='accept':
                require(set(payload)=={'draft_ref','review_ref'} and all(isinstance(v,str) for v in payload.values()),'INVALID_INPUT','确认版本无效'); command='accept'
            elif action=='cancel':
                require(not payload,'INVALID_INPUT','取消不能带额外参数'); command='cancel'
            else: raise DomainError('INVALID_INPUT','未知动作')
            run=self.server.store.command(run_id,owner,data['version'],data['key'],command,payload)
            self.send(200,view(run))
        except DomainError as error:
            status={'RESOURCE_NOT_FOUND':404,'AUTH_REQUIRED':401,'FORBIDDEN':403,'INVALID_INPUT':400}.get(error.code,409)
            self.send(status,{'error':{'code':error.code,'message':str(error)}})
        except Exception:
            # No raw provider, filesystem or document details leave the server.
            import traceback
            traceback.print_exc()
            self.send(500,{'error':{'code':'INTERNAL_ERROR','message':'操作失败，已保留原任务，请刷新后重试'}})


def main():
    parser=argparse.ArgumentParser(description='小红书四 Agent 本机模拟工作台')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--db',default='runtime/demo.sqlite')
    args=parser.parse_args(); Path(args.db).parent.mkdir(parents=True,exist_ok=True)
    server=DemoServer(('127.0.0.1',args.port),Store(args.db))
    print(f'模拟工作台：http://127.0.0.1:{server.server_port}（无需 API Key，仅本机）',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=='__main__': main()

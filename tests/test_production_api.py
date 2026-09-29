"""Run on SQLite and, when TEST_DATABASE_URL is set, a fresh PostgreSQL schema."""
import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from uuid import uuid4
from fastapi.testclient import TestClient
from backend.api import create_app
from backend.auth import Auth
from backend.contracts import DomainError
from backend.migrate import copy_database
from backend.provider import Config
from backend.store import Store
from backend.operations import Operations


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'site.sqlite')
        self.app=create_app(self.store,Config(),origin='http://testserver',invite='')
        self.client=TestClient(self.app)
        self.csrf=self.client.get('/api/session').json()['csrf']

    def tearDown(self):
        self.client.close();self.tmp.cleanup()

    def post(self, path, data, client=None, csrf=None):
        return (client or self.client).post(path,json=data,headers={'Origin':'http://testserver','X-CSRF-Token':csrf or self.csrf})

    def register(self, name='creator', password='Test-long-password', **extras):
        r=self.post('/api/auth/register',dict(username=name,password=password,**extras))
        self.assertEqual(r.status_code,200,r.text);self.csrf=r.json()['csrf'];return r.json()

    def brief(self):
        return dict(topic='整理衣橱',audience='大学生',tone='真实清楚',material='一件白衬衫可搭配已有衣物',scenario='standard',allow_hypothesis=True)

    def test_login_logout_fresh_device_and_no_password_leak(self):
        self.assertEqual(self.client.get('/api/operations').status_code,401)
        before=self.client.cookies.get('youji_session')
        identity=self.register()
        self.assertNotEqual(before,self.client.cookies.get('youji_session'))
        c=TestClient(self.app);csrf=c.get('/api/session').json()['csrf']
        r=self.post('/api/auth/login',{'username':'creator','password':'Test-long-password'},c,csrf)
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['user'],identity['user'])
        self.assertNotIn('password',r.text)
        token=self.client.cookies.get('youji_session')
        self.post('/api/auth/logout',{})
        self.assertIsNone(self.app.state.auth.session(token))
        self.assertEqual(c.get('/api/operations').status_code,200)
        c.close()

    def test_cross_user_and_csrf_run_ownership(self):
        self.register();r=self.post('/api/runs',self.brief());self.assertEqual(r.status_code,201,r.text)
        run=r.json()
        self.assertEqual(self.client.post('/api/runs',json=self.brief()).status_code,403)
        self.assertEqual(self.client.get('/api/session',headers={'Host':'evil.test'}).status_code,403)
        self.post('/api/auth/logout',{});self.csrf=self.client.get('/api/session').json()['csrf'];self.register('another')
        self.assertEqual(self.client.get('/api/runs/'+run['run_id']).status_code,404)
        self.assertEqual(self.client.get('/api/runs').json(),[])

    def test_background_endpoint_auth_idempotency_and_worker_completion(self):
        from backend.worker import Worker
        self.register();run=self.post('/api/runs',self.brief()).json()
        path='/api/runs/'+run['run_id']+'/background'
        command=dict(action='start',version=run['status_version'],key='background-test')
        self.assertEqual(self.client.post(path,json=command).status_code,403)
        for _ in range(2):
            response=self.post(path,command);self.assertEqual(response.status_code,202,response.text)
        self.assertEqual(response.json()['background']['status'],'queued')
        self.assertEqual(self.app.state.store.get(run['run_id'],self.app.state.auth.session(self.client.cookies.get('youji_session'))['owner']).drafts,[])
        Worker(self.app.state.service).once()
        run=self.client.get('/api/runs/'+run['run_id']).json()
        self.assertEqual(run['background']['status'],'waiting')
        self.assertEqual(run['wait_reason'],'final_confirmation')
        self.assertEqual(run['usage']['model_calls'],0)
        self.post('/api/auth/logout',{});self.csrf=self.client.get('/api/session').json()['csrf'];self.register('background_other')
        self.assertEqual(self.post(path,command).status_code,404)

    def test_quick_background_runtime_skips_professional_stages(self):
        from backend.worker import Worker
        self.register();brief=self.brief()|{'workflow':'quick'}
        run=self.post('/api/runs',brief).json()
        path='/api/runs/'+run['run_id']+'/background'
        response=self.post(path,{'action':'start','version':run['status_version'],'key':'quick-background'})
        self.assertEqual(response.status_code,202,response.text)
        Worker(self.app.state.service).once()
        run=self.client.get('/api/runs/'+run['run_id']).json()
        self.assertEqual(run['wait_reason'],'final_confirmation')
        self.assertEqual([n['stage'] for n in run['node_runs']],['quick','review'])
        self.assertEqual([a['stage'] for a in run['artifacts']],['quick'])
        self.assertEqual(run['branches'],{})

    def test_password_reset_revokes_sessions_and_rotates_recovery(self):
        identity=self.register();old_token=self.client.cookies.get('youji_session')
        data={'username':'creator','password':'New-long-password','recovery_code':identity['recovery_code']}
        r=self.post('/api/auth/reset',data);self.assertEqual(r.status_code,200,r.text)
        self.assertNotEqual(identity['recovery_code'],r.json()['recovery_code'])
        self.assertIsNone(self.app.state.auth.session(old_token))
        self.csrf=r.json()['csrf'];self.assertEqual(self.post('/api/auth/reset',data).status_code,401)

    def test_new_password_policy_boundaries_and_reset(self):
        invalid=['Aa12345','Aa'+'1'*19,'abcdefgh','ABCDEFGH','12345678']
        for i,password in enumerate(invalid):
            with self.subTest(password_case=i):
                r=self.post('/api/auth/register',dict(username='invalid'+str(i),password=password))
                self.assertEqual(r.status_code,400,r.text)
                self.assertIn('8–20',r.json()['error']['message'])
        for size,password in ((8,'Abcdefgh'),(20,'Ab'+'c'*18)):
            identity=self.register('boundary'+str(size),password=password)
            r=self.post('/api/auth/login',dict(username='boundary'+str(size),password=password))
            self.assertEqual(r.status_code,200,r.text);self.csrf=r.json()['csrf']
            old_token=self.client.cookies.get('youji_session')
            data=dict(username='boundary'+str(size),password='lowercaseonly',recovery_code=identity['recovery_code'])
            self.assertEqual(self.post('/api/auth/reset',data).status_code,400)
            self.assertIsNotNone(self.app.state.auth.session(old_token))
            data['password']='Xyabcdef' if size==20 else 'Xy'+'z'*18
            r=self.post('/api/auth/reset',data)
            self.assertEqual(r.status_code,200,r.text);self.csrf=r.json()['csrf']
            r=self.post('/api/auth/login',dict(username=data['username'],password=data['password']))
            self.assertEqual(r.status_code,200,r.text);self.csrf=r.json()['csrf']

    def test_existing_passwords_remain_verifiable_after_policy_change(self):
        self.register()
        for password in ('old-lowercase-pass','Old-password-longer-than-twenty'):
            salt='abcd'*8
            encoded=salt+':'+hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
            with self.store.connect() as db:
                db.execute('UPDATE users SET password_hash=? WHERE username=?',(encoded,'creator'))
            r=self.post('/api/auth/login',dict(username='creator',password=password))
            self.assertEqual(r.status_code,200,r.text);self.csrf=r.json()['csrf']
            self.assertEqual(self.post('/api/auth/login',dict(username='creator',password='WrongPassword')).status_code,401)

    def test_legacy_claim_is_explicit_and_once(self):
        token='legacy-token';owner='old-space'
        with self.store.connect() as db:
            db.execute('CREATE TABLE demo_sessions(token_hash TEXT PRIMARY KEY,owner TEXT,csrf TEXT)')
            db.execute('INSERT INTO demo_sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),owner,'old'))
        original=self.store.create(owner,'snapshot',self.brief())
        self.client.cookies.set('xhs_demo',token)
        self.register(claim_legacy=True)
        self.assertEqual(self.client.get('/api/runs').json()[0]['run_id'],original.run_id)
        self.post('/api/auth/logout',{});self.csrf=self.client.get('/api/session').json()['csrf']
        self.assertEqual(self.post('/api/auth/register',dict(username='second',password='Test-long-password',claim_legacy=True)).status_code,409)

    def test_workflow_edit_review_accept_and_idempotency(self):
        self.register();run=self.post('/api/runs',self.brief()).json()
        self.assertEqual(self.client.get('/api/runs/'+run['run_id']+'/bundle').status_code,409)
        def act(action,payload=None):
            nonlocal run
            body={'action':action,'version':run['status_version'],'key':str(uuid4()),'payload':payload or {}}
            url='/api/runs/'+run['run_id']+'/actions'
            r=self.post(url,body);self.assertEqual(r.status_code,200,r.text)
            replay=self.post(url,body);self.assertEqual(replay.json(),r.json())
            run=r.json()
        for _ in range(10):
            if run['run_status']=='WAITING_USER': break
            act('next')
        old=run['drafts'][-1]
        act('edit',{**old['content'],'selected_title':'从已有衣物开始整理'})
        self.assertNotIn('accept',run['allowed_actions'])
        act('next');act('accept',{'draft_ref':run['drafts'][-1]['ref'],'review_ref':run['review']['ref']})
        self.assertEqual(run['run_status'],'SUCCEEDED')
        self.assertEqual(self.client.get('/api/runs/'+run['run_id']+'/export').status_code,200)
        bundle=self.client.get('/api/runs/'+run['run_id']+'/bundle')
        self.assertEqual(bundle.status_code,200,bundle.text)
        self.assertEqual(bundle.headers['content-type'],'application/zip')
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            self.assertEqual(set(archive.namelist()),{'content.md','cover-copy.txt','publish-checklist.md','metadata.json'})
            metadata=json.loads(archive.read('metadata.json').decode('utf-8'))
            self.assertEqual(metadata['draft_ref'],run['accepted_ref'])
            self.assertEqual(metadata['review_ref'],run['review']['ref'])
            self.assertIn('不会自动发布',archive.read('publish-checklist.md').decode('utf-8'))
            self.assertNotIn('DEEPSEEK_API_KEY',bundle.content.decode('utf-8',errors='ignore'))

    def test_rate_limit_and_public_config(self):
        auth=self.app.state.auth
        auth.throttle('test',1)
        with self.assertRaises(DomainError): auth.throttle('test',1)
        with self.assertRaises(DomainError): create_app(self.store,Config(),origin='http://public.example',invite='')

    def test_frontend_assets_have_browser_executable_content_types(self):
        self.assertEqual(self.client.get('/app.js').headers['content-type'],'text/javascript; charset=utf-8')
        self.assertEqual(self.client.get('/promotion.js').headers['content-type'],'text/javascript; charset=utf-8')
        self.assertEqual(self.client.get('/style.css').headers['content-type'],'text/css; charset=utf-8')

    def test_promotion_brief_enters_run_as_public_snapshot(self):
        self.register();state=self.client.get('/api/operations').json();account=state['accounts'][0]
        def operation(action,payload):
            nonlocal state
            response=self.post('/api/operations',{'action':action,'payload':payload,'version':state['version'],'key':str(uuid4())})
            self.assertEqual(response.status_code,200,response.text);state=response.json();return state
        service=operation('save_service',{'id':'','account_id':account['id'],'name':'校园摄影','offering':'毕业照拍摄',
            'target_customer':'本校毕业生','delivery':'校内线下','price':'299 元起','availability':'仅周末','contact':'',
            'public_fields':['offering','target_customer','delivery','price'],'active':True})['services'][0]
        portfolio=operation('save_portfolio',{'id':'','service_id':service['id'],'title':'图书馆样片','description':'双人毕业照',
            'role':'独立拍摄和修图','facts':'在图书馆外拍摄','link':'','public_confirmed':True,'active':True})['portfolio_items'][0]
        brief=operation('create_promotion_brief',{'account_id':account['id'],'service_id':service['id'],'goal':'trust',
            'customer_problem':'不会摆姿势怎么办','problem_source':'user_provided','portfolio_ids':[portfolio['id']]})['promotion_briefs'][0]
        payload=self.brief()|{'operations':{'account_id':account['id'],'promotion_brief_id':brief['id']}}
        response=self.post('/api/runs',payload);self.assertEqual(response.status_code,201,response.text)
        context=response.json()['context'];self.assertEqual(context['operations']['promotion']['id'],brief['id'])
        self.assertIn('299 元起',context['material']);self.assertNotIn('仅周末',context['material'])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM account_records WHERE kind='promotion_briefs'").fetchone()[0],1)

    def test_invalid_body_is_safe_and_cookie_is_http_only(self):
        response=self.client.get('/api/session')
        self.assertIn('HttpOnly',response.headers['set-cookie'])
        r=self.post('/api/auth/login',[])
        self.assertEqual(r.status_code,400)
        self.assertEqual(r.json()['error']['code'],'INVALID_INPUT')

    def test_account_relational_projection(self):
        identity=self.register();state=self.client.get('/api/operations').json()
        r=self.post('/api/operations',{'action':'load_sample','payload':{},'version':state['version'],'key':'sample'})
        self.assertEqual(r.status_code,200,r.text)
        with self.store.connect() as db:
            self.assertGreater(db.execute('SELECT COUNT(*) FROM social_accounts').fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM account_records WHERE kind='publications'").fetchone()[0],4)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'PostgreSQL integration requires TEST_DATABASE_URL')
class PostgresProductionTests(ProductionTests):
    def setUp(self):
        import psycopg
        self.tmp=tempfile.TemporaryDirectory();self.schema='youji_test_'+uuid4().hex
        self.base=os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base,autocommit=True) as db: db.execute('CREATE SCHEMA '+self.schema)
        self.target=self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema
        self.store=Store(self.target)
        self.app=create_app(self.store,Config(),origin='http://testserver',invite='')
        self.client=TestClient(self.app);self.csrf=self.client.get('/api/session').json()['csrf']

    def tearDown(self):
        import psycopg
        super().tearDown()
        with psycopg.connect(self.base,autocommit=True) as db: db.execute('DROP SCHEMA '+self.schema+' CASCADE')

    def test_migration_preserves_rows_repeats_and_rejects_changed_target(self):
        source=Path(self.tmp.name)/'source.sqlite';s=Store(source);op=Operations(s)
        s.create('legacy-owner','snapshot',self.brief())
        op.command('legacy-owner',{'action':'load_sample','payload':{},'version':0,'key':'sample'})
        report=copy_database(source,self.target);self.assertTrue(report['verified'])
        self.assertEqual(copy_database(source,self.target),report)
        with self.store.connect() as db: db.execute("UPDATE runs SET payload='{}'")
        with self.assertRaises(DomainError): copy_database(source,self.target)

"""Run on SQLite and, when TEST_DATABASE_URL is set, a fresh PostgreSQL schema."""
import hashlib
import json
import os
import tempfile
import unittest
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

    def register(self, name='creator', **extras):
        r=self.post('/api/auth/register',dict(username=name,password='test-long-password',**extras))
        self.assertEqual(r.status_code,200,r.text);self.csrf=r.json()['csrf'];return r.json()

    def brief(self):
        return dict(topic='整理衣橱',audience='大学生',tone='真实清楚',material='一件白衬衫可搭配已有衣物',scenario='standard',allow_hypothesis=True)

    def test_login_logout_fresh_device_and_no_password_leak(self):
        self.assertEqual(self.client.get('/api/operations').status_code,401)
        before=self.client.cookies.get('youji_session')
        identity=self.register()
        self.assertNotEqual(before,self.client.cookies.get('youji_session'))
        c=TestClient(self.app);csrf=c.get('/api/session').json()['csrf']
        r=self.post('/api/auth/login',{'username':'creator','password':'test-long-password'},c,csrf)
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

    def test_password_reset_revokes_sessions_and_rotates_recovery(self):
        identity=self.register();old_token=self.client.cookies.get('youji_session')
        data={'username':'creator','password':'new-long-password','recovery_code':identity['recovery_code']}
        r=self.post('/api/auth/reset',data);self.assertEqual(r.status_code,200,r.text)
        self.assertNotEqual(identity['recovery_code'],r.json()['recovery_code'])
        self.assertIsNone(self.app.state.auth.session(old_token))
        self.csrf=r.json()['csrf'];self.assertEqual(self.post('/api/auth/reset',data).status_code,401)

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
        self.assertEqual(self.post('/api/auth/register',dict(username='second',password='test-long-password',claim_legacy=True)).status_code,409)

    def test_workflow_edit_review_accept_and_idempotency(self):
        self.register();run=self.post('/api/runs',self.brief()).json()
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

    def test_rate_limit_and_public_config(self):
        auth=self.app.state.auth
        auth.throttle('test',1)
        with self.assertRaises(DomainError): auth.throttle('test',1)
        with self.assertRaises(DomainError): create_app(self.store,Config(),origin='http://public.example',invite='')

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

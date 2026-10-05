"""Reversible run deletion through authenticated HTTP on SQLite and PostgreSQL."""
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from backend.api import create_app
from backend.provider import Config
from backend.store import Store


class VisibilityChecks:
    def setup_app(self, target):
        self.target = str(target)
        self.store = Store(self.target)
        self.app = create_app(self.store, Config(), origin='http://testserver', invite='')
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.csrf = self.client.get('/api/session').json()['csrf']

    def post(self, path, data):
        return self.client.post(path, json=data,
            headers={'Origin': 'http://testserver', 'X-CSRF-Token': self.csrf})

    def register(self, name='visibility_creator'):
        response = self.post('/api/auth/register', {'username': name, 'password': 'Visibility-test-1'})
        self.assertEqual(response.status_code, 200, response.text)
        self.csrf = response.json()['csrf']

    def create(self):
        response = self.post('/api/runs', {'topic': '整理衣橱', 'audience': '大学生', 'tone': '真实清楚',
            'material': '白衬衫搭配已有衣物', 'scenario': 'standard', 'allow_hypothesis': True, 'mode': 'simulation'})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def action(self, run, name, payload=None):
        response = self.post('/api/runs/' + run['run_id'] + '/actions',
            {'action': name, 'version': run['status_version'], 'key': uuid4().hex, 'payload': payload or {}})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_delete_restore_persist_and_keep_confirmed_export(self):
        self.register()
        run = self.create()
        for _ in range(10):
            if run['run_status'] == 'WAITING_USER':
                break
            run = self.action(run, 'next')
        run = self.action(run, 'accept', {'draft_ref': run['drafts'][-1]['ref'], 'review_ref': run['review']['ref']})
        root = '/api/runs/' + run['run_id']
        exported = self.client.get(root + '/export')
        self.assertEqual(exported.status_code, 200)
        before = self.client.get(root).json()
        for _ in range(2):
            response = self.post(root + '/visibility', {'deleted': True})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {'run_id':run['run_id'], 'deleted':True})
        self.assertEqual(self.client.get('/api/runs').json(), [])
        self.assertEqual([r['run_id'] for r in self.client.get('/api/runs?deleted=true').json()], [run['run_id']])
        self.assertEqual(self.client.get(root).json(), before)
        self.assertEqual(self.client.get(root + '/export').content, exported.content)
        # New app + repository uses persisted visibility, not process memory.
        cookies = dict(self.client.cookies)
        restarted = TestClient(create_app(Store(self.target), Config(), origin='http://testserver', invite=''))
        self.addCleanup(restarted.close)
        restarted.cookies.update(cookies)
        self.assertEqual(restarted.get('/api/runs').json(), [])
        self.assertEqual(len(restarted.get('/api/runs?deleted=true').json()), 1)
        self.assertEqual(self.post(root + '/visibility', {'deleted':False}).status_code, 200)
        self.assertEqual(len(restarted.get('/api/runs').json()), 1)
        self.assertEqual(restarted.get('/api/runs?deleted=true').json(), [])

    def test_auth_csrf_cross_owner_and_strict_input(self):
        self.assertEqual(self.client.get('/api/runs?deleted=true').status_code, 401)
        self.assertEqual(self.post('/api/runs/unknown/visibility', {'deleted':True}).status_code, 401)
        self.register()
        run = self.action(self.create(), 'cancel')
        path = '/api/runs/' + run['run_id'] + '/visibility'
        self.assertEqual(self.client.post(path, json={'deleted':True}).status_code, 403)
        for body in ({}, {'deleted':'true'}, {'deleted':1}, {'deleted':None}, {'deleted':True,'owner':'other'}):
            self.assertEqual(self.post(path, body).status_code, 400, body)
        self.assertEqual(self.post(path, {'deleted':True}).status_code, 200)
        self.post('/api/auth/logout', {})
        self.csrf = self.client.get('/api/session').json()['csrf']
        self.register('visibility_other')
        self.assertEqual(self.client.get('/api/runs?deleted=true').json(), [])
        self.assertEqual(self.post(path, {'deleted':False}).status_code, 404)
        self.assertEqual(self.post('/api/runs/nonexistent/visibility', {'deleted':True}).status_code, 404)

    def test_delete_active_run_cancels_and_restore_does_not_restart(self):
        self.register()
        run = self.create()
        response = self.post('/api/runs/' + run['run_id'] + '/visibility', {'deleted':True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/api/runs').json(), [])
        self.assertEqual(self.client.get('/api/runs?deleted=true').json()[0]['run_status'], 'CANCELLED')
        self.assertEqual(self.post('/api/runs/' + run['run_id'] + '/visibility', {'deleted':False}).status_code,200)
        self.assertEqual(self.client.get('/api/runs').json()[0]['run_status'],'CANCELLED')

    def test_delete_fences_pending_worker_even_with_terminal_run(self):
        self.register()
        run = self.create()
        path = '/api/runs/' + run['run_id']
        response = self.post(path + '/background', {'action':'start', 'version':run['status_version'], 'key':uuid4().hex})
        self.assertEqual(response.status_code, 202, response.text)
        run = self.action(response.json(), 'cancel')
        with self.store.connect() as db:
            db.execute("UPDATE runtime_jobs SET status='running' WHERE run_id=?", (run['run_id'],))
        response = self.post(path + '/visibility', {'deleted':True})
        self.assertEqual(response.status_code, 200)
        with self.store.connect() as db:
            row=db.execute('SELECT status,token,lease_until FROM runtime_jobs WHERE run_id=?',(run['run_id'],)).fetchone()
        self.assertEqual(tuple(row),('done',None,None))


class SQLiteVisibilityTests(VisibilityChecks, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.setup_app(Path(temporary.name) / 'visibility.sqlite')


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires actual PostgreSQL TEST_DATABASE_URL')
class PostgresVisibilityTests(VisibilityChecks, unittest.TestCase):
    def setUp(self):
        import psycopg
        base = os.environ['TEST_DATABASE_URL']
        schema = 'visibility_test_' + uuid4().hex
        with psycopg.connect(base, autocommit=True) as db:
            db.execute('CREATE SCHEMA ' + schema)
        def cleanup():
            with psycopg.connect(base, autocommit=True) as db:
                db.execute('DROP SCHEMA ' + schema + ' CASCADE')
        self.addCleanup(cleanup)
        self.setup_app(base + ('&' if '?' in base else '?') + 'options=-csearch_path%3D' + schema)

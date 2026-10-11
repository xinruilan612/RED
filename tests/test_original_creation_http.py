"""HTTP/SQL/worker acceptance. Deterministic unpaid model and vector fixtures.

This proves routing and persistence; live model quality is assessed separately.
"""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from backend.api import create_app
from backend.knowledge import Knowledge
from backend.live import schema
from backend.provider import Config
from backend.store import Store
from backend.worker import Worker
from original_creation_cases import CASES, METHOD


class RoutingVectors:
    max_chunks=256
    minimum_similarity=0.1
    def encode(self,texts):return [[1.,0.] for _ in texts]


class OriginalFixtureModel:
    def __init__(self):self.calls=[]
    def complete(self,messages):
        stage=re.search(r'负责 (\w+) 的',messages[0]['content']).group(1)
        data=json.loads(messages[1]['content']);self.calls.append((stage,data))
        value=schema(stage);source=data['materials'][0]
        examples=data['retrieved_references']
        note=(examples[0]['source_id']+'：借鉴开篇问题，不移植经历。') if examples else '无匹配样例，仅按方法和本题事实创作。'
        if stage=='audience':value['basis']=note
        if stage=='research':value.update(facts=[{'source_id':source['source_id'],'quote':source['text']}],prohibited_claims=[note])
        if stage=='strategy':value['why_account']=note
        if stage=='body':value.update(selected_title='候选一',body=source['text'])
        if stage=='review':
            value['limitations']=[note];value['checks'][-2]['result']='unknown'
            value['claim_map']=[{'excerpt':source['text'],'quote':source['text'],'source_id':source['source_id']}]
        return value,100


class OriginalCreationHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(str(Path(self.temp.name)/'http.sqlite'))
    def tearDown(self):self.temp.cleanup()

    def test_classification_endpoint_keeps_original_and_requires_owner_version_csrf(self):
        with patch('backend.api.settings',return_value={}):
            app=create_app(self.store,Config(),origin='http://testserver',invite='')
        with TestClient(app) as client:
            csrf=client.get('/api/session').json()['csrf']
            def post(url,data):
                return client.post(url,json=data,headers={'Origin':'http://testserver','X-CSRF-Token':csrf})
            response=post('/api/auth/register',{'username':'classification_http','password':'Test-long-password'})
            self.assertEqual(response.status_code,200);csrf=response.json()['csrf']
            account=client.get('/api/operations').json()['accounts'][0]['id']
            doc=post('/api/knowledge',dict(account_id=account,title='美妆资料',text='面霜净含量30毫升。')).json()
            doc=client.get('/api/knowledge/'+doc['id'],params={'account_id':account}).json()
            path='/api/knowledge/'+doc['id']+'/classification'
            payload=dict(account_id=account,version=doc['version'],classification=dict(
                domains=['beauty'],channel='any',format='any',material_type='fact'))
            self.assertEqual(client.post(path,json=payload).status_code,403)
            updated=post(path,payload)
            self.assertEqual(updated.status_code,200,updated.text)
            self.assertEqual(updated.json()['version'],doc['version']+1)
            self.assertEqual(updated.json()['fingerprint'],doc['fingerprint'])
            self.assertEqual(updated.json()['chunks'][0]['text'],doc['chunks'][0]['text'])
            self.assertEqual(post(path,payload).json()['error']['code'],'VERSION_CONFLICT')
            payload['version']+=1;payload['account_id']='foreign-account'
            self.assertEqual(post(path,payload).status_code,404)

    def test_six_cases_http_worker_three_groups_and_audit(self):
        model=OriginalFixtureModel()
        with patch('backend.api.settings',return_value={}):
            app=create_app(self.store,Config('fixture-never-sent'),origin='http://testserver',invite='',client=model)
        app.state.service.knowledge=Knowledge(self.store,embedding_provider=RoutingVectors())
        with TestClient(app) as client:
            csrf=client.get('/api/session').json()['csrf']
            def post(url,data):return client.post(url,json=data,headers={'Origin':'http://testserver','X-CSRF-Token':csrf})
            response=post('/api/auth/register',{'username':'original_http','password':'Test-long-password'})
            self.assertEqual(response.status_code,200,response.text);csrf=response.json()['csrf']
            taxonomy=client.get('/api/creation/taxonomy').json()
            self.assertIn('beauty',taxonomy['domains'])
            account=client.get('/api/operations').json()['accounts'][0]['id']
            def save(title,text,domains,kind,form='note',channel='xiaohongshu'):
                response=post('/api/knowledge',dict(account_id=account,title=title,text=text,
                    classification=dict(domains=domains,material_type=kind,channel=channel,format=form)))
                self.assertEqual(response.status_code,200,response.text)
                return response.json()['id']
            save('通用方法',METHOD,['general'],'method','any','any')
            for case in CASES:
                if case['sample']:save(case['name']+'样例',case['sample'],[case['domain']],'example',case['format'])
                if case['facts']:save(case['product']+'事实',case['facts'],[case['domain']],'fact','any','any')
            for case in CASES:
                with self.subTest(case=case['name']):
                    before=len(model.calls)
                    response=post('/api/runs',dict(topic=case['topic'],audience='新手',tone='清楚',material='',allow_hypothesis=True,
                        mode='live',creation=dict(domains=[case['domain']],channel='xiaohongshu',format=case['format'],word_count=180),
                        knowledge=dict(enabled=True,automatic_references=True),operations=dict(account_id=account,platform='xiaohongshu',account='测试账号')))
                    self.assertEqual(response.status_code,201,response.text);run=response.json();identity=run['run_id']
                    groups=run['context']['creation_retrieval']['groups']
                    self.assertTrue(groups['facts']);self.assertTrue(groups['methods'])
                    self.assertEqual(bool(groups['examples']),bool(case['sample']))
                    for source in groups['examples']:
                        self.assertIn(case['domain'],source['classification']['domains'])
                        self.assertEqual(source['classification']['format'],case['format'])
                    self.assertIsNone(run['context']['creation_retrieval']['filters']['facts']['channel'])
                    response=post('/api/runs/'+identity+'/background',dict(action='start',version=run['status_version'],key=uuid4().hex))
                    self.assertEqual(response.status_code,202,response.text)
                    Worker(app.state.service).once()
                    run=client.get('/api/runs/'+identity).json()
                    self.assertEqual(run['wait_reason'],'final_confirmation',run)
                    self.assertEqual(len(model.calls)-before,8)
                    audit=run['review']['reference_records']
                    self.assertEqual(audit['example_gap'],not bool(case['sample']))
                    self.assertTrue(audit['claim_map'])
                    for stage,data in model.calls[before:]:
                        self.assertEqual(data['creation_classification']['format'],case['format'])
                        self.assertEqual(data['creation_classification']['domains'],[case['domain']])
                        self.assertEqual({s['source_id'] for s in data['materials']},set(audit['groups']['facts']))
                        self.assertTrue(all('text' not in s for s in data['retrieved_references']))
                    response=post('/api/runs/'+identity+'/actions',dict(action='cancel',version=run['status_version'],key=uuid4().hex,payload={}))
                    self.assertEqual(response.status_code,200,response.text)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'requires real isolated PostgreSQL schema')
class PostgresOriginalCreationHTTPTests(OriginalCreationHTTPTests):
    def setUp(self):
        import psycopg
        self.temp=tempfile.TemporaryDirectory();self.base=os.environ['TEST_DATABASE_URL'];self.schema='youji_original_http_'+uuid4().hex
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('CREATE SCHEMA '+self.schema)
        self.store=Store(self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema)
    def tearDown(self):
        import psycopg
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('DROP SCHEMA '+self.schema+' CASCADE')
        self.temp.cleanup()

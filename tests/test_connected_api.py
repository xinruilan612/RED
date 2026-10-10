"""HTTP integration for owner-scoped model/search/research workflows; no paid traffic."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from backend.api import create_app
from backend.contracts import DomainError
from backend.provider import Config
from backend.store import Store
from backend.worker import Worker


class ConnectedHarness:
    def prepare(self):
        environment=patch.dict(os.environ,{'MODEL_CREDENTIAL_KEY':Fernet.generate_key().decode(),'YOUJI_EMBEDDING_MODEL_PATH':''})
        environment.start();self.addCleanup(environment.stop)
        self.app=create_app(self.store,Config(),origin='http://testserver',invite='')
        self.client,self.csrf,self.owner=self.register('creator')
        self.account=self.client.get('/api/operations').json()['accounts'][0]['id']

    def register(self,name):
        client=TestClient(self.app);self.addCleanup(client.close)
        csrf=client.get('/api/session').json()['csrf']
        response=client.post('/api/auth/register',json={'username':name,'password':'Test-long-password'},
                             headers={'Origin':'http://testserver','X-CSRF-Token':csrf})
        self.assertEqual(response.status_code,200,response.text)
        csrf=response.json()['csrf'];owner=self.app.state.auth.session(client.cookies.get('youji_session'))['owner']
        return client,csrf,owner

    def post(self,url,data,client=None,csrf=None):
        return (client or self.client).post(url,json=data,headers={'Origin':'http://testserver','X-CSRF-Token':csrf or self.csrf})

    def model(self):
        response=self.post('/api/models/connections',dict(provider='qwen',model='test-model',api_key='private-api-key',
                            rate_usd_per_million=2,run_budget_usd=1,day_budget_usd=5))
        self.assertEqual(response.status_code,200,response.text);return response.json()

    def case(self,**extra):
        return dict(account_id=self.account,title='护肤表达参考',text='保湿乳液案例正文，先介绍使用场景再解释选择方法。表达结构供创作参考，不能当作用户产品的功效证明。',
                    source_url='https://brand.example/article',permission_confirmed=True,evidence_role='expression_reference',**extra)

    def job(self,**extra):
        data=dict(account_id=self.account,queries=['保湿乳液'],provider='bing',targets=['web'],
                  evidence_role='expression_reference',permission_confirmed=True,key=str(uuid4()))
        data.update(extra);return data


class ConnectedAPITests(ConnectedHarness,unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.store=Store(Path(temporary.name)/'api.sqlite');self.prepare()

    def test_session_model_selection_revoke_csrf_and_owner_isolation(self):
        self.assertFalse(self.client.get('/api/session').json()['provider']['ready'])
        item=self.model();url='/api/models/default'
        self.assertEqual(self.client.post(url,json={'connection_id':item['id']}).status_code,403)
        self.assertEqual(self.post(url,{'connection_id':item['id']}).status_code,200)
        session=self.client.get('/api/session').json()
        self.assertTrue(session['provider']['ready']);self.assertEqual(session['provider']['model'],'test-model')
        self.assertEqual(session['provider']['billing_source'],'user');self.assertNotIn('private-api-key',json.dumps(session))
        other,csrf,_=self.register('other')
        self.assertEqual(other.get('/api/models').json()['connections'],[])
        self.assertNotEqual(self.post(url,{'connection_id':item['id']},other,csrf).status_code,200)
        self.assertNotEqual(self.post('/api/models/connections/'+item['id']+'/delete',{'version':1},other,csrf).status_code,200)
        self.assertEqual(self.post('/api/models/connections/'+item['id']+'/delete',{'version':1}).status_code,200)
        self.assertFalse(self.client.get('/api/session').json()['provider']['ready'])
        self.assertEqual(self.client.get('/api/session').json()['provider']['billing_source'],'user')
        self.assertEqual(self.post(url,{'connection_id':None}).status_code,200)
        self.assertEqual(self.client.get('/api/session').json()['provider']['billing_source'],'platform')

    def test_connection_probe_requires_explicit_cost_ack_and_sanitizes_failure(self):
        item=self.model();url='/api/models/connections/'+item['id']+'/test'
        with patch('backend.provider.ConnectedModel.complete_result',return_value=({'ok':True},21,{})) as complete:
            self.assertEqual(self.post(url,{'version':1,'acknowledge_cost':False}).status_code,400)
            complete.assert_not_called()
            response=self.post(url,{'version':1,'acknowledge_cost':True})
            self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['tokens'],21)
        self.assertNotIn('private-api-key',response.text)
        self.assertEqual(self.client.get('/api/models').json()['connections'][0]['test_status'],'passed')

    def test_search_settings_quota_failures_encryption_and_other_owner_block(self):
        data=dict(api_key='private-search-api-key',enabled=True,version=0,day_limit=1,acknowledge_cost=True)
        self.assertEqual(self.client.post('/api/search/settings',json=data).status_code,403)
        response=self.post('/api/search/settings',data);self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn('private-search-api-key',response.text)
        query=dict(account_id=self.account,query='保湿乳液',provider='baidu',targets=['jd'])
        with patch('backend.search_providers.request_baidu',side_effect=DomainError('SOURCE_UNAVAILABLE','provider failed')) as request:
            failed=self.post('/api/sources/search',query)
            self.assertNotEqual(failed.status_code,200)
            exhausted=self.post('/api/sources/search',query)
            self.assertEqual(exhausted.json()['error']['code'],'BUDGET_EXCEEDED');self.assertEqual(request.call_count,1)
        self.assertEqual(self.client.get('/api/search/settings').json()['baidu']['requests_today'],1)
        with self.store.connect() as db:
            self.assertNotIn('private-search-api-key',db.execute('SELECT secret FROM search_connections').fetchone()[0])
        other,csrf,_=self.register('other')
        self.assertFalse(other.get('/api/search/settings').json()['baidu']['configured'])
        with patch('backend.search_providers.request_baidu') as request:
            self.assertEqual(self.post('/api/sources/search',query,other,csrf).status_code,404);request.assert_not_called()

    def test_cases_retrieve_export_and_cross_account_visibility(self):
        response=self.post('/api/research/cases',self.case(metrics={'likes':1500},observed_at='2026-01-02T00:00:00Z',published_at='2026-01-01T00:00:00Z'))
        self.assertEqual(response.status_code,200,response.text);item=response.json()
        self.assertNotIn('original_base64',item);self.assertNotIn('versions',item)
        results=self.post('/api/knowledge/retrieve',dict(account_id=self.account,query='保湿乳液')).json()
        self.assertEqual(results['sources'][0]['case_ref']['document_id'],item['id'])
        self.assertEqual(results['sources'][0]['evidence_role'],'expression_reference')
        exported=self.client.get('/api/research/cases/export',params={'account_id':self.account})
        self.assertEqual(exported.status_code,200,exported.text);self.assertIn('attachment',exported.headers['content-disposition'])
        self.assertIn('护肤表达参考',exported.text)
        other,_,_=self.register('other')
        self.assertEqual(other.get('/api/research/cases',params={'account_id':self.account}).status_code,404)
        self.assertEqual(other.get('/api/research/cases/export',params={'account_id':self.account}).status_code,404)

    def test_restricted_url_import_is_rejected_before_fetch(self):
        with patch('backend.sources.read_article') as reader:
            for url in ('https://www.xiaohongshu.com/explore/123','https://xhslink.com/123'):
                response=self.post('/api/research/cases/import-url',dict(account_id=self.account,url=url,evidence_role='expression_reference',permission_confirmed=True))
                self.assertEqual(response.json()['error']['code'],'SOURCE_PERMISSION_REQUIRED')
                response=self.post('/api/sources/import',dict(account_id=self.account,url=url))
                self.assertEqual(response.json()['error']['code'],'SOURCE_PERMISSION_REQUIRED')
            reader.assert_not_called()

    def test_research_api_worker_persists_cases_and_report_no_paid_model(self):
        packet=self.job();response=self.post('/api/research/jobs',packet)
        self.assertEqual(response.status_code,202,response.text);identity=response.json()['id']
        self.assertEqual(self.post('/api/research/jobs',packet).json()['id'],identity)
        other,csrf,_=self.register('other')
        self.assertEqual(other.get('/api/research/jobs/'+identity).status_code,404)
        self.assertEqual(self.post('/api/research/jobs/'+identity+'/cancel',{},other,csrf).status_code,404)
        article=dict(url='https://brand.example/research',title='保湿乳液研究',text='保湿乳液案例资料，表达参考强调使用场景和清晰表达。此正文只是研究材料，不证明其他产品功效。',
                     fetched_at='2026-01-02T00:00:00Z',verification='public_body',published_at=None)
        with patch('backend.research_jobs.SearchSettings.search',return_value={'results':[{'url':article['url'],'title':article['title']}]}),patch('backend.research_jobs.read_article',return_value=article),patch('backend.provider.DeepSeek.complete_result') as model:
            self.assertTrue(Worker(self.app.state.service).once());model.assert_not_called()
        job=self.client.get('/api/research/jobs/'+identity).json()
        self.assertEqual(job['status'],'done',job);self.assertEqual(len(job['documents']),1)
        exported=self.client.get('/api/research/jobs/'+identity+'/export')
        self.assertEqual(exported.status_code,200,exported.text);self.assertIn('保湿乳液研究',exported.text)
        self.assertNotIn('token',job);self.assertNotIn('private-search-api-key',exported.text)
        results=self.post('/api/knowledge/retrieve',dict(account_id=self.account,query='保湿乳液')).json()
        self.assertEqual(results['sources'][0]['case_ref']['document_id'],job['documents'][0]['id'])
        cancelled=self.post('/api/research/jobs',self.job()).json()['id']
        self.assertEqual(self.post('/api/research/jobs/'+cancelled+'/cancel',{}).json()['status'],'cancelled')
        with patch('backend.research_jobs.SearchSettings.search') as search:
            self.assertFalse(Worker(self.app.state.service).once());search.assert_not_called()


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'requires actual PostgreSQL')
class PostgresConnectedAPITests(ConnectedHarness,unittest.TestCase):
    def setUp(self):
        import psycopg
        base=os.environ['TEST_DATABASE_URL'];schema='connected_api_'+uuid4().hex
        with psycopg.connect(base,autocommit=True) as db:db.execute('CREATE SCHEMA '+schema)
        def cleanup():
            with psycopg.connect(base,autocommit=True) as db:db.execute('DROP SCHEMA '+schema+' CASCADE')
        self.addCleanup(cleanup)
        target=base+('&' if '?' in base else '?')+'options=-csearch_path%3D'+schema
        self.store=Store(target);self.prepare()

    test_session_model_selection_revoke_csrf_and_owner_isolation=ConnectedAPITests.test_session_model_selection_revoke_csrf_and_owner_isolation
    test_cases_retrieve_export_and_cross_account_visibility=ConnectedAPITests.test_cases_retrieve_export_and_cross_account_visibility
    test_research_api_worker_persists_cases_and_report_no_paid_model=ConnectedAPITests.test_research_api_worker_persists_cases_and_report_no_paid_model

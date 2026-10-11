"""HTTP authorization, replay and download contract for content windtunnel."""
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from fastapi.testclient import TestClient
from backend.api import create_app
from backend.provider import Config
from backend.store import Store
from backend.worker import Worker
from backend.operations import now


class WindtunnelApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'http.sqlite')
        self.app=create_app(self.store,Config(),origin='http://testserver',invite='')
        self.client=TestClient(self.app)
        self.register('wind_http_user')
        self.account=self.client.get('/api/operations').json()['accounts'][0]['id']

    def tearDown(self):self.client.close();self.tmp.cleanup()
    def post(self,path,data):
        return self.client.post(path,json=data,headers={'Origin':'http://testserver','X-CSRF-Token':self.csrf})
    def register(self,name):
        self.csrf=self.client.get('/api/session').json()['csrf']
        response=self.post('/api/auth/register',{'username':name,'password':'Test-Password-2026'})
        self.assertEqual(response.status_code,200,response.text)
        self.csrf=response.json()['csrf']
    def create(self,**extra):
        response=self.post('/api/runs',{'workflow_type':'windtunnel','account_id':self.account,'title':'本地工具导出教程','text':'打开工具，导出结果。','mode':'simulation',**extra})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()
    def advance(self,run):
        response=self.post('/api/runs/'+run['run_id']+'/background',{'action':'start','version':run['status_version'],'key':uuid4().hex})
        self.assertEqual(response.status_code,202,response.text)
        Worker(self.app.state.service).once()
        return self.client.get('/api/runs/'+run['run_id']).json()
    def action(self,run,action,payload):
        response=self.post('/api/runs/'+run['run_id']+'/actions',{'action':action,'version':run['status_version'],'key':uuid4().hex,'payload':payload})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_http_full_report_download_and_checklist_idempotency(self):
        run=self.advance(self.create())
        cs=run['windtunnel']['condition_sets'][-1]
        run=self.action(run,'confirm_conditions',{'condition_set_id':cs['id'],'condition_hash':cs['hash']})
        run=self.advance(run)
        self.assertEqual(run['wait_reason'],'wt_report',run['background'])
        command={'run_id':run['run_id'],'condition_set_id':cs['id'],'title':'可复用工具教程检查','key':uuid4().hex,'version':run['status_version']}
        saved=self.post('/api/windtunnel/checklists',command)
        self.assertEqual(saved.status_code,200,saved.text)
        replay=self.post('/api/windtunnel/checklists',command)
        self.assertEqual(replay.json(),saved.json())
        rows=self.client.get('/api/windtunnel/checklists',params={'account_id':self.account}).json()
        self.assertEqual(len(rows),1)
        download=self.client.get('/api/runs/'+run['run_id']+'/export')
        self.assertEqual(download.status_code,200,download.text)
        self.assertIn('attachment',download.headers['content-disposition'])
        self.assertIn('模拟流程',download.text)
        target=Path(self.tmp.name)/'download.md';target.write_bytes(download.content)
        self.assertIn('本地工具导出教程',target.read_text())
        finished=self.action(run,'finish',{})
        reused=self.create(checklist={'id':saved.json()['id'],'version':saved.json()['version']})
        self.assertEqual(reused['wait_reason'],'wt_confirm_conditions')
        self.assertFalse(reused['windtunnel']['condition_sets'][-1]['confirmed'])
        self.assertEqual(finished['run_status'],'SUCCEEDED')

    def test_cross_user_run_sources_checklists_and_csrf(self):
        run=self.advance(self.create());cs=run['windtunnel']['condition_sets'][-1]
        run=self.action(run,'confirm_conditions',{'condition_set_id':cs['id'],'condition_hash':cs['hash']})
        run=self.advance(run)
        self.assertEqual(self.client.post('/api/runs',json={}).status_code,403)
        own=self.account
        self.post('/api/auth/logout',{});self.register('wind_http_other')
        self.account=self.client.get('/api/operations').json()['accounts'][0]['id']
        self.assertEqual(self.client.get('/api/runs/'+run['run_id']).status_code,404)
        self.assertEqual(self.client.get('/api/runs/'+run['run_id']+'/export').status_code,404)
        self.assertEqual(self.client.get('/api/windtunnel/checklists',params={'account_id':own}).status_code,404)
        forbidden=self.post('/api/runs/'+run['run_id']+'/actions',dict(action='cancel',version=run['status_version'],key='bad',payload={}))
        self.assertEqual(forbidden.status_code,404)
        saved=self.post('/api/windtunnel/checklists',dict(run_id=run['run_id'],condition_set_id=cs['id'],title='偷取',version=run['status_version'],key='steal'))
        self.assertEqual(saved.status_code,404)
        self.assertEqual(self.client.get('/api/runs').json(),[])

    def test_live_is_disabled_and_workbench_assets_serve(self):
        response=self.post('/api/runs',dict(workflow_type='windtunnel',account_id=self.account,title='教程',text='步骤',mode='live'))
        self.assertEqual(response.status_code,409)
        self.assertEqual(response.json()['error']['code'],'LIVE_DISABLED')
        for path in ('/windtunnel.js','/windtunnel.css'):
            self.assertEqual(self.client.get(path).status_code,200,path)
        self.assertNotIn('windtunnel',self.client.get('/').text)
        self.assertEqual(self.client.get('/.env').status_code,404)

    def test_recheck_cannot_export_previous_batch(self):
        run=self.advance(self.create());cs=run['windtunnel']['condition_sets'][-1]
        run=self.action(run,'confirm_conditions',{'condition_set_id':cs['id'],'condition_hash':cs['hash']})
        run=self.advance(run)
        self.action(run,'recheck',{'condition_set_id':cs['id']})
        response=self.client.get('/api/runs/'+run['run_id']+'/export')
        self.assertEqual(response.status_code,409)

    def test_signal_hypothesis_creation_and_windtunnel_are_bound(self):
        state=self.client.get('/api/operations').json()
        signal_payload=dict(account_id=self.account,kind='comment_demand',text='如何把剪辑好的文件导出？',
            source_url='',observed_at=now(),sample_size=8,collection_method='manual',notes='授权测试摘要')
        signal=self.post('/api/operations',dict(action='add_signal',payload=signal_payload,
            version=state['version'],key=uuid4().hex))
        self.assertEqual(signal.status_code,200,signal.text)
        state=signal.json();entry=state['signals'][0]
        payload=dict(account_id=self.account,objective='lead_acquisition',audience='剪辑软件新手',
            statement='完整步骤能提高有效试用注册',desired_action='完成试用注册',metric='signups',
            window='24h',minimum_lift_pct=20,falsifier='注册率提升低于20%',signal_ids=[entry['id']])
        created=self.post('/api/operations',dict(action='create_hypothesis',payload=payload,
            version=state['version'],key=uuid4().hex))
        self.assertEqual(created.status_code,200,created.text)
        hypothesis=created.json()['hypotheses'][0]
        self.assertEqual(hypothesis['denominator'],'link_clicks')
        run_response=self.post('/api/runs',dict(topic='剪辑导出步骤',audience='新手',tone='清楚',mode='simulation',
            operations=dict(platform='xiaohongshu',account_id=self.account,hypothesis_id=hypothesis['id'])))
        self.assertEqual(run_response.status_code,201,run_response.text)
        self.assertEqual(run_response.json()['context']['operations']['active_hypothesis']['id'],hypothesis['id'])
        wind=self.create(hypothesis_id=hypothesis['id'])
        self.assertEqual(wind['windtunnel']['hypothesis_id'],hypothesis['id'])
        self.assertEqual(self.client.get('/trials.js').status_code,200)
        self.assertEqual(self.client.get('/trials.css').status_code,200)

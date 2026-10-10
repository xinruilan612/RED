"""End-to-end HTTP tests against an ephemeral loopback demo server."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from backend.store import Store
from backend.web import DemoServer, Handler


class DemoWebTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'demo.sqlite')
        self.server=DemoServer(('127.0.0.1',0),self.store)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.cookie=''; self.csrf=''
        self.logs=patch.object(Handler,'log_message',lambda *args:None); self.logs.start()
        self.request('GET','/api/session')

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.logs.stop(); self.temp.cleanup()

    def request(self,method,path,data=None,headers=None):
        client=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        hdr={'Cookie':self.cookie,'Origin':f'http://127.0.0.1:{self.server.server_port}',
             'Content-Type':'application/json','X-CSRF-Token':self.csrf}
        hdr.update(headers or {})
        try:
            client.request(method,path,json.dumps(data) if data is not None else None,hdr)
            response=client.getresponse(); body=response.read()
            cookie=response.getheader('Set-Cookie')
            if cookie: self.cookie=cookie.split(';')[0]
            result=json.loads(body) if response.getheader('Content-Type','').startswith('application/json') else body.decode()
            if path=='/api/session' and response.status==200:self.csrf=result['csrf']
            return response.status,result
        finally:client.close()

    def create(self,scenario='standard',**overrides):
        data={'topic':'整理资料','audience':'学生','tone':'清楚','material':'','scenario':scenario,'allow_hypothesis':True}
        data.update(overrides)
        status,run=self.request('POST','/api/runs',data); self.assertEqual(status,201,run)
        return run

    def action(self,run,action,payload=None,expect=200,key=None):
        status,result=self.request('POST',f"/api/runs/{run['run_id']}/actions",{'action':action,'payload':payload or {},'version':run['status_version'],'key':key or str(uuid4())})
        self.assertEqual(status,expect,result)
        return result

    def until_pause(self,run):
        for _ in range(12):
            if run['run_status']=='WAITING_USER' or (run['review'] and run['review']['decision']=='revision_required'):return run
            run=self.action(run,'next')
        self.fail('模拟任务没有在有限步骤内暂停')

    def test_create_step_accept_export_and_replay(self):
        run=self.create(); initial=run
        status,_=self.request('GET',f"/api/runs/{run['run_id']}/export");self.assertEqual(status,409)
        run=self.action(run,'next',key='first-step')
        replay=self.action(initial,'next',key='first-step');self.assertEqual(run,replay)
        self.assertEqual(len(run['node_runs']),2)
        self.assertEqual({n['agent'] for n in run['node_runs']},{'audience','research'})
        run=self.until_pause(run)
        self.assertEqual(run['wait_reason'],'final_confirmation')
        self.assertEqual([a['stage'] for a in run['artifacts']],['strategy','outline','hook','title','body'])
        self.assertEqual(run['usage']['model_calls'],0)
        before=run
        payload={'draft_ref':run['drafts'][-1]['ref'],'review_ref':run['review']['ref']}
        run=self.action(run,'accept',payload,key='accept-once')
        self.assertEqual(run['run_status'],'SUCCEEDED')
        self.assertEqual(self.action(before,'accept',payload,key='accept-once'),run)
        status,body=self.request('GET',f"/api/runs/{run['run_id']}/export")
        self.assertEqual(status,200);self.assertIn('未调用真实 AI',body)
        status,loaded=self.request('GET',f"/api/runs/{run['run_id']}")
        self.assertEqual(run,loaded)

    def test_manual_revision_then_reaudit_keeps_versions(self):
        run=self.until_pause(self.create('revision'))
        self.assertEqual(run['review']['decision'],'revision_required')
        self.assertIn('edit',run['allowed_actions'])
        old=run['drafts'][-1]
        content=dict(old['content']);content['selected_title']='从整理一条资料开始'
        run=self.action(run,'edit',content)
        self.assertEqual(run['drafts'][0],old)
        self.assertEqual(run['drafts'][-1]['actor'],'user')
        self.assertNotIn('accept',run['allowed_actions'])
        self.action(run,'accept',{'draft_ref':old['ref'],'review_ref':'old'},expect=409)
        run=self.action(run,'next')
        self.assertEqual(run['review']['previous_issue_results'][0]['result'],'resolved')
        self.assertEqual(run['wait_reason'],'final_confirmation')

    def test_automatic_revision_and_old_version_rejection(self):
        run=self.until_pause(self.create('revision'));old=run
        run=self.action(run,'next');self.assertEqual(len(run['drafts']),2)
        self.assertNotIn('必爆',run['drafts'][-1]['content']['selected_title'])
        self.action(old,'next',expect=409)
        run=self.action(run,'next')
        self.assertEqual(run['review']['decision'],'approved')
        self.action(run,'accept',{'draft_ref':run['drafts'][0]['ref'],'review_ref':run['review']['ref']},expect=409)

    def test_material_and_permission_pause_are_visible(self):
        run=self.create('missing');run=self.action(run,'next')
        self.assertEqual(run['wait_reason'],'missing_material')
        self.action(run,'supplement',{'material':'','allow_hypothesis':True},expect=400)
        old_snapshot=run['snapshot_id']
        run=self.action(run,'supplement',{'material':'我把笔记按课程分类。','allow_hypothesis':True})
        self.assertNotEqual(run['snapshot_id'],old_snapshot)
        self.assertEqual(run['branches'],{})
        run=self.until_pause(run);self.assertEqual(run['wait_reason'],'final_confirmation')
        self.assertIn('我把笔记按课程分类',run['drafts'][-1]['content']['body'])
        self.action(run,'cancel')
        run=self.action(self.create(allow_hypothesis=False),'next')
        self.assertEqual(run['wait_reason'],'hypothesis_permission')
        self.action(run,'supplement',{'material':'','allow_hypothesis':False},expect=400)
        run=self.action(run,'supplement',{'material':'','allow_hypothesis':True})
        self.assertEqual(run['run_status'],'QUEUED')

    def test_csrf_origin_host_and_cross_session_isolation(self):
        run=self.create()
        data={'action':'next','version':0,'key':'bad','payload':{}}
        path=f"/api/runs/{run['run_id']}/actions"
        for headers in ({'X-CSRF-Token':'bad'},{'Origin':'https://example.com'},{'Host':'malicious.invalid'}):
            status,_=self.request('POST',path,data,headers);self.assertEqual(status,403)
        self.cookie='';self.request('GET','/api/session')
        status,_=self.request('GET',f"/api/runs/{run['run_id']}");self.assertEqual(status,404)
        status,rows=self.request('GET','/api/runs');self.assertEqual(rows,[])
        status,_=self.request('POST',path,data);self.assertEqual(status,404)

    def test_private_commands_and_untrusted_fields_rejected(self):
        run=self.create()
        self.action(run,'reviewed',{'gates':{}},expect=409)
        self.action(run,'next',{'run_status':'SUCCEEDED'},expect=400)
        status,_=self.request('POST','/api/runs',{'topic':'x','owner_id':'other'})
        self.assertEqual(status,400)
        status,_=self.request('GET','/../../backend/store.py');self.assertEqual(status,404)
        self.action(run,'cancel')
        self.action(run,'next',expect=409)

    def test_operations_http_csrf_context_and_isolation(self):
        status,state=self.request('GET','/api/operations')
        self.assertEqual(status,200)
        self.assertEqual(len(state['trends']),4)
        self.assertEqual(state['publications'],[])
        data={'action':'add_trend','payload':{'title':'测试选题','platform':'xiaohongshu',
              'category':'学习','angle':'操作过程','source_url':'https://example.com/topic',
              'observed_at':'2020-01-01T00:00:00Z'},'version':0,'key':'add-trend'}
        status,_=self.request('POST','/api/operations',data,{'X-CSRF-Token':'bad'})
        self.assertEqual(status,403)
        status,state=self.request('POST','/api/operations',data)
        self.assertEqual(status,200)
        trend=state['trends'][0]
        run=self.create(operations={'platform':'xiaohongshu','account':'演示账号','trend_id':trend['id']})
        self.assertEqual(run['context']['operations']['trend']['source_url'],'https://example.com/topic')
        self.cookie='';self.request('GET','/api/session')
        status,state=self.request('GET','/api/operations')
        self.assertEqual(len(state['trends']),4)
        status,_=self.request('POST','/api/runs',{'topic':'x','audience':'x','tone':'x',
             'operations':{'trend_id':trend['id']}})
        self.assertEqual(status,404)

    def test_operations_navigation_and_static_script(self):
        status,html=self.request('GET','/')
        self.assertEqual(status,200)
        from html.parser import HTMLParser
        class Elements(HTMLParser):
            def __init__(self):super().__init__();self.ids=[];self.pages=[]
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if 'id' in attrs:self.ids.append(attrs['id'])
                if 'data-page' in attrs:self.pages.append(attrs['data-page'])
        parsed=Elements();parsed.feed(html)
        self.assertEqual(len(parsed.ids),len(set(parsed.ids)))
        self.assertEqual(parsed.pages,['overview','accounts','connections','models','research','library','trends','trials','windtunnel','studio','publish','metrics','memory'])
        status,script=self.request('GET','/operations.js')
        self.assertEqual(status,200);self.assertIn('/api/operations',script)

    def test_static_assets_and_unknown_routes(self):
        for path in ('/','/app.js','/style.css','/connections.js','/models.js','/research.js','/account_profile.js','/trials.js','/trials.css'):
            status,body=self.request('GET',path);self.assertEqual(status,200);self.assertTrue(body)
        status,html=self.request('GET','/')
        for label in ('协作流程','补充真实素材','保存新版本并等待复审','运行记录','模拟运行'):
            self.assertIn(label,html)
        # Parse the actual HTML, catching malformed option tags that strand startup JS.
        from html.parser import HTMLParser
        class Options(HTMLParser):
            def __init__(self):super().__init__();self.options=[]
            def handle_starttag(self,tag,attrs):
                if tag=='option':self.options.append(dict(attrs))
        parsed=Options();parsed.feed(html)
        self.assertTrue(any(o.get('id')=='liveOption' and o.get('value')=='live' for o in parsed.options))
        status,_=self.request('GET','/missing');self.assertEqual(status,404)


class LiveWebTests(unittest.TestCase):
    request=DemoWebTests.request
    create=DemoWebTests.create
    action=DemoWebTests.action
    until_pause=DemoWebTests.until_pause
    tearDown=DemoWebTests.tearDown

    def setUp(self):
        from backend.provider import Config
        from test_live_provider import FixtureModel
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'live.sqlite')
        self.model=FixtureModel()
        self.server=DemoServer(('127.0.0.1',0),self.store,Config('private-test-key'),self.model)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.cookie='';self.csrf=''
        self.logs=patch.object(Handler,'log_message',lambda *args:None);self.logs.start()
        self.request('GET','/api/session')

    def test_real_mode_http_creation_export_and_private_env(self):
        status,session=self.request('GET','/api/session')
        self.assertTrue(session['provider']['ready']);self.assertNotIn('private-test-key',json.dumps(session))
        status,_=self.request('GET','/.env');self.assertEqual(status,404)
        run=self.until_pause(self.create(mode='live'))
        self.assertEqual(run['mode'],'live');self.assertEqual(run['usage']['model_calls'],8)
        run=self.action(run,'accept',{'draft_ref':run['drafts'][-1]['ref'],'review_ref':run['review']['ref']})
        status,body=self.request('GET',f"/api/runs/{run['run_id']}/export")
        self.assertEqual(status,200);self.assertIn('AI 创作稿',body);self.assertNotIn('模拟创作稿',body)
        self.assertNotIn('private-test-key',json.dumps(run))

    def test_recover_live_failure_from_ui_contract_and_replay(self):
        base=self.model.complete
        def bad(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='outline':value={'items':[None,'two']}
            return value,tokens
        self.model.complete=bad
        run=self.create(mode='live')
        for _ in range(3):run=self.action(run,'next')
        self.assertEqual(run['run_status'],'FAILED');self.assertIn('recover',run['allowed_actions'])
        parent=run;run=self.action(parent,'recover')
        self.assertNotEqual(run['run_id'],parent['run_id'])
        self.assertEqual(self.action(parent,'recover')['run_id'],run['run_id'])
        self.assertEqual(run['usage']['model_calls'],4)
        self.model.complete=base
        run=self.until_pause(run)
        self.assertEqual(run['wait_reason'],'final_confirmation')
        self.assertEqual(run['usage']['model_calls'],9)

    def test_no_key_cannot_create_live_but_simulation_still_free(self):
        from backend.provider import Config
        self.server.config=Config()
        status,error=self.request('POST','/api/runs',{'mode':'live','topic':'x'})
        self.assertEqual(status,409);self.assertEqual(error['error']['code'],'KEY_REQUIRED')
        run=self.until_pause(self.create())
        self.assertEqual(run['mode'],'simulation');self.assertEqual(self.model.calls,[])

if __name__=='__main__':unittest.main()

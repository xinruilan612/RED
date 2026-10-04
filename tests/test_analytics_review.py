import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from backend.store import Store
from backend.service import Service
from backend.provider import Config
from backend.contracts import DomainError
from backend.analytics_review import plain_review
from backend.operations import now

class ReviewFixture:
    def __init__(self):self.calls=0;self.callback=None
    def complete_result(self,messages):
        self.calls+=1
        data=json.loads(messages[1]['content'])
        if self.callback:self.callback()
        return {'summary':'已有读者收藏这篇，先继续这个方向。','keep':'保留清楚的步骤。','change':'下一篇只增加一个具体例子，观察反馈。','next_topic':'洗脸之后如何安排护肤步骤','check_next':'记录下一篇同一时间的收藏与阅读。','basis_refs':data['available_basis_refs']},123,{'request_id':'review-fixture','input_tokens':80,'output_tokens':43}

class AnalyticsReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'review.sqlite');self.client=ReviewFixture();self.service=Service(self.store,Config(api_key='test-only'),self.client);self.ops=self.service.operations;self.owner='owner'
        self.command('save_account',{'id':'','name':'复盘验收账号','platform':'xiaohongshu','profile':{'positioning':'护肤','audience':'新手','tone':'清楚','pillars':'教程','goal':'关注','resources':'手机','banned':'','weekly_frequency':2}})
        self.account=self.ops.read(self.owner)['accounts'][-1]
        self.command('import_post',{'account_id':self.account['id'],'title':'洗脸后先做什么','body':'先按自己的情况保湿，再做好防晒。','tags':[],'url':'https://www.xiaohongshu.com/explore/test-review','published_at':now(),'format':'image_text','pillar':'教程','traffic':'organic'})
        self.post=self.ops.read(self.owner)['publications'][0]
        self.command('metrics',{'id':self.post['id'],'window':'24h','observed_at':now(),'views':19,'likes':2,'saves':5,'comments':0,'shares':None,'new_followers':None,'profile_visits':None,'completed_plays':None})
        self.metric=self.ops.read(self.owner)['metrics'][-1];self.command('analyze',{'id':self.metric['id']});self.report=self.ops.read(self.owner)['analyses'][0]
    def tearDown(self):self.tmp.cleanup()
    def command(self,action,payload):return self.ops.command(self.owner,{'action':action,'payload':payload,'version':self.ops.read(self.owner)['version'],'key':str(uuid4())})
    def request(self):return {'id':self.report['id'],'version':self.ops.read(self.owner)['version'],'key':str(uuid4()),'acknowledge':True}
    def test_first_post_has_useful_action_without_fake_baseline(self):
        state=self.ops.read(self.owner);plain=plain_review(state,self.report)
        self.assertIn('收藏',plain['summary']);self.assertIn('下一篇',plain['change']);self.assertTrue(plain['next_topic']);self.assertEqual(self.report['status'],'insufficient');self.assertIsNone(self.report['comparisons']['saves']['baseline']);self.assertIn('26.3',plain['observations'][0]);self.assertEqual(self.report['execution']['model_calls'],0)
    def test_real_call_audited_persisted_and_no_duplicate_charge(self):
        request=self.request();result=self.service.analytics_review.generate(self.owner,request)
        self.assertEqual(self.client.calls,1);self.assertEqual(result['review']['execution']['tokens'],123)
        self.service.analytics_review.generate(self.owner,self.request());self.assertEqual(self.client.calls,1)
        restored=Service(Store(self.store.path),Config(api_key='test-only'),self.client)
        self.assertEqual(restored.operations.read(self.owner)['analyses'][0]['ai_review'],result['review'])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM live_calls WHERE stage='analytics_review'").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT outcome FROM model_audit WHERE stage='analytics_review'").fetchone()[0],'validated')
    def test_explicit_consent_and_owner_isolation(self):
        req=self.request();req['acknowledge']=False
        with self.assertRaises(DomainError):self.service.analytics_review.generate(self.owner,req)
        with self.assertRaises(DomainError):self.service.analytics_review.generate('other',self.request())
        self.assertEqual(self.client.calls,0)
    def test_metric_correction_invalidates_old_ai_and_stops_paid_request(self):
        self.command('metrics',{'id':self.post['id'],'window':'24h','observed_at':now(),'views':20,'likes':2,'saves':5,'comments':0,'shares':None,'new_followers':None,'profile_visits':None,'completed_plays':None})
        with self.assertRaises(DomainError):self.service.analytics_review.generate(self.owner,self.request())
        self.assertEqual(self.client.calls,0)
    def test_change_during_call_preserves_original_without_old_result(self):
        self.client.callback=lambda:self.command('metrics',{'id':self.post['id'],'window':'24h','observed_at':now(),'views':21,'likes':2,'saves':5,'comments':0,'shares':None,'new_followers':None,'profile_visits':None,'completed_plays':None})
        with self.assertRaises(DomainError):self.service.analytics_review.generate(self.owner,self.request())
        self.assertNotIn('ai_review',self.ops.read(self.owner)['analyses'][0]);self.assertEqual(self.client.calls,1)
        with self.assertRaises(DomainError):self.service.analytics_review.generate(self.owner,self.request())
        self.assertEqual(self.client.calls,1)
    def test_missing_key_keeps_free_review(self):
        service=Service(self.store,Config())
        with self.assertRaises(DomainError):service.analytics_review.generate(self.owner,self.request())
        self.assertTrue(plain_review(self.ops.read(self.owner),self.report)['change'])

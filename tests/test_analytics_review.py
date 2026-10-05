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
    def __init__(self):self.calls=0;self.callback=None;self.messages=None
    def complete_result(self,messages):
        self.calls+=1;self.messages=messages
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

    def test_existing_steps_question_and_sources_are_preserved_not_requested_again(self):
        state=self.ops.read(self.owner)
        state['publications'][0]['content']['body']='1. 先判断使用场景。\n2. 再按步骤操作。\n你在哪一步遇到问题？\n参考资料：https://example.com/guide'
        plain=plain_review(state,self.report)
        self.assertEqual(plain['content_checks'],dict(has_steps=True,has_question=True,has_source=True))
        self.assertIn('已有的步骤',plain['keep']);self.assertIn('结尾提问',plain['keep']);self.assertIn('资料出处',plain['keep'])
        self.assertIn('具体使用场景',plain['change']);self.assertNotIn('改成更清楚的步骤',plain['change'])
        self.assertIn('已有提问',plain['observations'][-1]);self.assertIn('不能据此判断收藏原因',plain['summary'])
        self.assertIn('19 次阅读',plain['summary']);self.assertIn('未记录曝光',plain['missing_evidence'][0])
        self.assertEqual(plain['next_plan']['change'],plain['change'])

    def test_late_record_uses_actual_elapsed_and_missing_followers_not_zero(self):
        state=self.ops.read(self.owner);report=dict(self.report,elapsed_hours=92.93,window_quality='late')
        state['metrics'][-1]['window']='72h'
        plain=plain_review(state,report)
        self.assertIn('92.93',plain['observation_period']);self.assertIn('72h',plain['observation_period'])
        self.assertIn('92.93',plain['check_next']);self.assertIn('24 小时、72 小时',plain['check_next'])
        self.assertFalse(any(c['label']=='因这篇作品关注你' for c in plain['counts']))
        self.assertTrue(any('关注' in text for text in plain['missing_evidence']))

    def test_ai_prompt_receives_text_checks_and_new_review_version(self):
        result=self.service.analytics_review.generate(self.owner,self.request())
        prompt=self.client.messages[0]['content'];snapshot=json.loads(self.client.messages[1]['content'])['snapshot']
        self.assertIn('原稿已有的步骤或提问',prompt);self.assertIn('实际观察时长',prompt)
        self.assertIn('content_checks',snapshot['calculations']);self.assertEqual(snapshot['post']['content'],self.post['content'])
        self.assertEqual(result['review']['review_version'],2)

"""Persistent operations loop and boundaries between demo and manual evidence."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from backend.contracts import DomainError
from backend.demo import validate_brief
from backend.operations import Operations, now
from backend.store import Store
from backend.workflow import digest


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'ops.sqlite')
        self.ops=Operations(self.store)
        self.owner='alice'

    def tearDown(self):self.temp.cleanup()

    def command(self, action, payload, owner=None):
        owner=owner or self.owner
        return self.ops.command(owner,dict(action=action,payload=payload,version=self.ops.read(owner)['version'],key=str(uuid4())))

    def confirmed(self,mode='simulation',platform='xiaohongshu'):
        context=validate_brief(dict(topic='衣橱搭配',audience='学生',tone='真实',material='我用白衬衫搭配蓝色牛仔裤。'))
        context.update(mode=mode,operations=self.ops.context(self.owner,dict(platform=platform,account='我的账号'),mode))
        run=self.store.create(self.owner,str(uuid4()),context)
        for _ in range(12):
            if run.run_status=='WAITING_USER':break
            run=self.store.command(run.run_id,self.owner,run.status_version,str(uuid4()),'demo_step')
        self.assertEqual(run.wait_reason,'final_confirmation')
        return self.store.command(run.run_id,self.owner,run.status_version,str(uuid4()),'accept',dict(draft_ref=run.drafts[-1]['ref'],review_ref=run.review['ref']))

    def publication(self,mode='simulation'):
        run=self.confirmed(mode)
        state=self.command('prepare',dict(run_id=run.run_id,draft_ref=run.accepted_ref))
        return run,state['publications'][0]

    def metrics(self,pub,**overrides):
        payload=dict(id=pub['id'],window='24h',views=1000,likes=30,saves=20,comments=10,shares=5,observed_at=now())
        payload.update(overrides)
        return self.command('metrics',payload)

    def test_persistent_loop_with_accepted_memory_and_revoke(self):
        run,pub=self.publication()
        self.command('approve',dict(id=pub['id']))
        self.command('simulate',dict(id=pub['id']))
        metric=self.metrics(pub)['metrics'][-1]
        state=self.command('learn',dict(id=metric['id']))
        memory=state['memories'][0]
        self.assertIn('6.5%',memory['observation'])
        self.assertEqual(memory['sample_size'],1)
        self.command('memory',dict(id=memory['id'],status='accepted'))
        restored=Operations(Store(self.store.path))
        self.assertEqual(restored.read(self.owner),self.ops.read(self.owner))
        context=restored.context(self.owner,dict(account='我的账号'), 'simulation')
        self.assertEqual(context['memories'][0]['metric_id'],metric['id'])
        next_run=self.confirmed()
        strategy=next(a['value'] for a in next_run.artifacts if a['stage']=='strategy')
        self.assertEqual(strategy['learning_refs'],[memory['id']])
        self.command('memory',dict(id=memory['id'],status='revoked'))
        self.assertEqual(self.ops.context(self.owner,{},'simulation')['memories'],[])

    def test_publication_requires_accepted_exact_version_and_separate_approval(self):
        context=validate_brief(dict(topic='衣橱',audience='学生',tone='清楚'))
        run=self.store.create(self.owner,'snapshot',context)
        with self.assertRaises(DomainError):self.command('prepare',dict(run_id=run.run_id,draft_ref='fake'))
        self.store.command(run.run_id,self.owner,0,'cancel','cancel')
        run,pub=self.publication()
        with self.assertRaises(DomainError):self.command('simulate',dict(id=pub['id']))
        with self.assertRaises(DomainError):self.command('prepare',dict(run_id=run.run_id,draft_ref='old'))
        self.command('approve',dict(id=pub['id']))
        with self.assertRaises(DomainError):self.command('record',dict(id=pub['id'],url='https://xiaohongshu.com/explore/test',published_at=now()))
        with self.assertRaises(DomainError):self.metrics(pub)

    def test_manual_post_link_and_live_simulation_separation(self):
        _,pub=self.publication('live')
        self.command('approve',dict(id=pub['id']))
        with self.assertRaises(DomainError):self.command('simulate',dict(id=pub['id']))
        with self.assertRaises(DomainError):self.command('record',dict(id=pub['id'],url='https://xiaohongshu.com.attacker.invalid/post',published_at=now()))
        state=self.command('record',dict(id=pub['id'],url='https://www.xiaohongshu.com/explore/test',published_at=now()))
        self.assertEqual(state['publications'][0]['status'],'MANUAL_REPORTED')
        metric=self.metrics(pub,views=None)['metrics'][-1]
        self.assertEqual(metric['source_type'],'manual')
        mem=self.command('learn',dict(id=metric['id']))['memories'][0]
        self.assertIn('不完整',mem['observation'])

    def test_simulated_memory_never_enters_live_or_other_account(self):
        _,pub=self.publication();self.command('approve',dict(id=pub['id']));self.command('simulate',dict(id=pub['id']))
        metric=self.metrics(pub)['metrics'][-1]
        memory=self.command('learn',dict(id=metric['id']))['memories'][0]
        self.command('memory',dict(id=memory['id'],status='accepted'))
        for mode,data in [('live',{}),('simulation',{'account':'其他账号'}),('simulation',{'platform':'douyin'})]:
            self.assertEqual(self.ops.context(self.owner,data,mode)['memories'],[])
        with self.assertRaises(DomainError):self.ops.context(self.owner,{'trend_id':'example-0'},'live')

    def test_metrics_correction_invalidates_memory_without_double_counting(self):
        _,pub=self.publication();self.command('approve',dict(id=pub['id']));self.command('simulate',dict(id=pub['id']))
        metric=self.metrics(pub,likes=None)['metrics'][-1]
        memory=self.command('learn',dict(id=metric['id']))['memories'][0]
        self.assertIn('不完整',memory['observation'])
        self.command('memory',dict(id=memory['id'],status='accepted'))
        state=self.metrics(pub,likes=0)
        self.assertEqual(len(state['metrics']),2)
        self.assertEqual(state['metrics'][-1]['revision'],2)
        self.assertEqual(state['metrics'][0]['values']['likes'],None)
        self.assertEqual(state['memories'][0]['status'],'superseded')
        with self.assertRaises(DomainError):self.command('learn',dict(id=metric['id']))
        with self.assertRaises(DomainError):self.metrics(pub,likes=True)
        with self.assertRaises(DomainError):self.metrics(pub,views=-2)
        with self.assertRaises(DomainError):self.metrics(pub,observed_at='2000-01-01T00:00:00Z')

    def test_cross_owner_and_duplicate_commands(self):
        run,pub=self.publication()
        for action,payload in [('prepare',dict(run_id=run.run_id,draft_ref=run.accepted_ref)),('approve',dict(id=pub['id']))]:
            with self.assertRaises(DomainError):self.command(action,payload,owner='bob')
        self.assertEqual(self.ops.read('bob')['publications'],[])
        command=dict(action='approve',payload={'id':pub['id']},version=self.ops.read(self.owner)['version'],key='same')
        first=self.ops.command(self.owner,command)
        self.assertEqual(self.ops.command(self.owner,command),first)
        with self.assertRaises(DomainError):self.ops.command(self.owner,{**command,'key':'new-key'})
        with self.assertRaises(DomainError):self.ops.command(self.owner,{**command,'action':'simulate'})
        with self.assertRaises(DomainError):self.command('prepare',dict(run_id=run.run_id,draft_ref=run.accepted_ref))

    def test_trend_provenance_and_time_validation(self):
        payload=dict(title='白衬衫',platform='xiaohongshu',category='穿搭',angle='三种场景',source_url='https://example.com/a',observed_at=now())
        state=self.command('add_trend',payload)
        trend=state['trends'][0]
        self.assertEqual(trend['source_type'],'manual')
        self.assertEqual(self.ops.context(self.owner,dict(trend_id=trend['id']),'live')['trend'],trend)
        with self.assertRaises(DomainError):self.command('add_trend',payload)
        for key,value in [('source_url','javascript:alert(1)'),('observed_at','tomorrow'),('observed_at','2099-01-01T00:00:00Z')]:
            with self.assertRaises(DomainError):self.command('add_trend',{**payload,key:value,'title':'different'})
        self.assertIsNone(state['trends'][1]['observed_at'])

    def test_douyin_is_script_not_video(self):
        run=self.confirmed(platform='douyin')
        self.assertIn('非成片',run.drafts[-1]['content']['body'])
        self.assertIn('0–3 秒',run.drafts[-1]['content']['body'])

    def archive_payload(self, run, **overrides):
        payload=dict(run_id=run.run_id,draft_ref=run.accepted_ref,title='实际发出的标题',
            body='博主在小红书最终发布的文字',tags=['衣橱记录'],
            url='https://www.xiaohongshu.com/explore/actual',published_at=now())
        return {**payload,**overrides}

    def test_archive_actual_content_and_source_audit_without_approval(self):
        run=self.confirmed('live')
        payload=self.archive_payload(run)
        state=self.command('archive_published',payload)
        pub=state['publications'][0]
        self.assertEqual(pub['status'],'MANUAL_REPORTED')
        self.assertIsNone(pub['approved_at'])
        self.assertIsNone(pub['acceptance'])
        self.assertIsNone(pub['review_ref'])
        self.assertEqual(pub['source_acceptance'],run.acceptance)
        self.assertEqual(pub['source_content'],run.drafts[-1]['content'])
        self.assertEqual(pub['source_content_hash'],digest(run.drafts[-1]['content']))
        self.assertEqual(pub['content']['body'],payload['body'])
        self.assertEqual(pub['content']['tags'],payload['tags'])
        self.assertEqual(pub['content_hash'],digest(pub['content']))
        self.assertNotEqual(pub['content_hash'],pub['source_content_hash'])
        self.assertEqual(self.command('archive_published',payload)['publications'],[pub])
        self.assertEqual(Operations(Store(self.store.path)).read(self.owner)['publications'],[pub])
        self.assertEqual(self.metrics(pub)['metrics'][-1]['source_type'],'manual')

    def test_archive_reuses_legacy_queue_and_is_idempotent(self):
        for approved in (False,True):
            run,pub=self.publication('live')
            if approved:self.command('approve',dict(id=pub['id']))
            payload=self.archive_payload(run,url='https://www.xiaohongshu.com/explore/'+run.run_id)
            command=dict(action='archive_published',payload=payload,
                version=self.ops.read(self.owner)['version'],key=str(uuid4()))
            first=self.ops.command(self.owner,command)
            self.assertEqual(self.ops.command(self.owner,command),first)
            archived=next(p for p in first['publications'] if p['id']==pub['id'])
            self.assertEqual(archived['status'],'MANUAL_REPORTED')
            self.assertEqual(len([p for p in first['publications'] if p['run_id']==run.run_id]),1)

    def test_archive_accepts_xhs_cn_share_text_and_normalizes_duplicate_link(self):
        run=self.confirmed('live')
        link='https://xhslink.cn/o/8ZZwcVOCe77?xsec_token=a%2Bb&source=share'
        payload=self.archive_payload(run,url='洗脸后先涂什么？ ['+link+'] Copy and open rednote to view the note')
        pub=self.command('archive_published',payload)['publications'][0]
        self.assertEqual(pub['url'],link)
        self.assertEqual(pub['status'],'MANUAL_REPORTED')
        self.assertEqual(self.command('archive_published',{**payload,'url':link})['publications'],[pub])

    def test_share_link_extraction_keeps_platform_and_single_link_guards(self):
        from backend.operations import url
        self.assertEqual(url('分享：https://xhslink.cn/o/post。复制打开','xiaohongshu'),'https://xhslink.cn/o/post')
        self.assertEqual(url('抖音 https://v.douyin.com/post/ 复制打开','douyin'),'https://v.douyin.com/post/')
        for value in ('https://xhslink.cn.evil.example/o/a','https://xhslink.cn@evil.example/o/a',
                      'https://evil.example@xhslink.cn/o/a','https://v.douyin.com/a',
                      'https://xhslink.cn/a https://xhslink.cn/b','javascript:alert(1)'):
            with self.subTest(value=value),self.assertRaises(DomainError):url(value,'xiaohongshu')

    def test_archive_manually_adopted_draft_keeps_unresolved_review_on_source_only(self):
        context=validate_brief(dict(topic='衣橱',audience='学生',tone='真实',material='本人记录',scenario='revision'))
        context.update(mode='live',operations=self.ops.context(self.owner,{},'live'))
        run=self.store.create(self.owner,str(uuid4()),context)
        for _ in range(8):
            if run.review:break
            run=self.store.command(run.run_id,self.owner,run.status_version,str(uuid4()),'demo_step')
        self.assertEqual(run.review['decision'],'revision_required')
        run=self.store.command(run.run_id,self.owner,run.status_version,str(uuid4()),'adopt_manual',
            dict(draft_ref=run.drafts[-1]['ref'],content_hash=run.drafts[-1]['content_hash'],acknowledge=True))
        pub=self.command('archive_published',self.archive_payload(run))['publications'][0]
        self.assertEqual(pub['source_acceptance']['mode'],'manual_override')
        self.assertTrue(pub['source_acceptance']['acknowledged_issues'])
        self.assertIsNone(pub['acceptance'])
        self.assertIsNone(pub['review_ref'])
        self.assertEqual(pub['status'],'MANUAL_REPORTED')

    def test_archive_rejects_bad_source_owner_fields_and_duplicate_links_atomically(self):
        simulation=self.confirmed()
        with self.assertRaises(DomainError):self.command('archive_published',self.archive_payload(simulation))
        run=self.confirmed('live');payload=self.archive_payload(run)
        for bad in ({'draft_ref':'old'},{'tags':'tag'},{'tags':[1]},
                    {'url':'https://evil.invalid/post'},{'published_at':'2099-01-01T00:00:00Z'}):
            with self.assertRaises(DomainError):self.command('archive_published',{**payload,**bad})
        with self.assertRaises(DomainError):self.command('archive_published',payload,owner='bob')
        self.assertEqual(self.ops.read(self.owner)['publications'],[])
        self.command('archive_published',payload)
        with self.assertRaises(DomainError):self.command('archive_published',{**payload,'body':'不同作品'})
        other=self.confirmed('live')
        with self.assertRaises(DomainError):self.command('archive_published',self.archive_payload(other))
        self.assertEqual(len(self.ops.read(self.owner)['publications']),1)

    def test_import_tags_and_account_scoped_duplicate_links(self):
        run=self.confirmed('live')
        pub=self.command('archive_published',self.archive_payload(run))['publications'][0]
        payload=dict(account_id=pub['account_id'],title='自行创作的笔记',body='实际正文',tags=['记录'],
            url=pub['url'],published_at=now(),format='image_text',pillar='日常',traffic='unknown')
        with self.assertRaises(DomainError):self.command('import_post',payload)
        imported=self.command('import_post',{**payload,'url':'https://xhslink.com/another'})['publications'][0]
        self.assertEqual(imported['content']['tags'],['记录'])
        self.assertIsNone(imported['run_id'])
        self.assertEqual(imported['status'],'MANUAL_REPORTED')
        from backend.accounts import PROFILE_FIELDS
        account=self.command('save_account',dict(id='',name='另一个账号',platform='xiaohongshu',
            profile={**{k:'' for k in PROFILE_FIELDS},'weekly_frequency':3}))['accounts'][-1]
        another=self.command('import_post',{**payload,'account_id':account['id']})['publications'][0]
        self.assertEqual(another['account_id'],account['id'])


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires actual PostgreSQL')
class PostgresOperationsTests(OperationsTests):
    def setUp(self):
        import psycopg
        self.schema='youji_ops_archive_test_'+uuid4().hex
        self.base=os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('CREATE SCHEMA '+self.schema)
        target=self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema
        self.store=Store(target);self.ops=Operations(self.store);self.owner='alice'

    def tearDown(self):
        import psycopg
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('DROP SCHEMA '+self.schema+' CASCADE')


if __name__=='__main__':unittest.main()

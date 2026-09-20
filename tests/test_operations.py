"""Persistent operations loop and boundaries between demo and manual evidence."""
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from backend.contracts import DomainError
from backend.demo import validate_brief
from backend.operations import Operations, now
from backend.store import Store


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


if __name__=='__main__':unittest.main()

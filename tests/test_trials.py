"""Evidence gates for signal-to-hypothesis and the three trial stages."""
import json
import os
from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from backend.contracts import DomainError
from backend.operations import Operations, now
from backend.store import Store
from backend.workflow import Run


class ContentTrialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(getattr(self, 'database_url', Path(self.tmp.name) / 'trials.sqlite'))
        self.ops = Operations(self.store)
        self.owner = 'creator-a'
        self.account = self.ops.read(self.owner)['accounts'][0]['id']
        self.signal = self.command('add_signal', dict(account_id=self.account, kind='search_intent',
            text='字幕导出在哪里设置？', source_url='', observed_at=now(), sample_size=12,
            collection_method='manual', notes='一周内手工归纳并去标识'))['signals'][0]
        self.hyp = self.command('create_hypothesis', dict(account_id=self.account, objective='lead_acquisition',
            audience='第一次使用剪辑工具的新手', statement='完整字幕步骤比单讲功能更能带来试用注册',
            desired_action='进入试用页并完成注册', metric='signups', window='24h', minimum_lift_pct=20,
            falsifier='观察窗结束后注册率提升不足 20%', signal_ids=[self.signal['id']]))['hypotheses'][0]

    def tearDown(self):
        self.tmp.cleanup()

    def command(self, action, payload, owner=None):
        owner = owner or self.owner
        return self.ops.command(owner, dict(action=action, payload=payload,
            version=self.ops.read(owner)['version'], key=uuid4().hex))

    def persist_run(self, run):
        with self.store.connect() as db:
            db.execute('INSERT INTO runs(id,owner,payload) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                       (run.run_id, run.owner_id, json.dumps(asdict(run), ensure_ascii=False)))
        return run

    def make_run(self, ref, workflow='creation', hypothesis_id=None):
        run = Run(owner_id=self.owner, snapshot_id=uuid4().hex,
            context={'mode':'live','operations':{'account_id':self.account,'hypothesis_id':hypothesis_id}})
        run.workflow_type = workflow
        run.run_status = 'SUCCEEDED'
        run.drafts = [dict(ref=ref, content_hash='hash-'+ref,
            content={'selected_title':'字幕教程 '+ref, 'body':'完整步骤'})]
        if workflow == 'windtunnel':
            run.windtunnel = dict(account_id=self.account, hypothesis_id=hypothesis_id,
                drafts=[dict(hash='wind-draft-hash')], reports=[dict(id='report-1', batch_id='batch-1',
                    draft_hash='wind-draft-hash', condition_hash='condition-hash', mode='simulation',
                    results=[dict(status='pass'), dict(status='unclear')])])
        self.persist_run(run)
        return run

    def record_wind_and_race(self):
        wind = self.make_run('wind-ref', workflow='windtunnel', hypothesis_id=self.hyp['id'])
        self.command('record_trial', dict(hypothesis_id=self.hyp['id'], level='windtunnel',
            payload={'run_id':wind.run_id,'notes':'规则替身预演'}))
        a, b = self.make_run('draft-a',hypothesis_id=self.hyp['id']), self.make_run('draft-b',hypothesis_id=self.hyp['id'])
        invalid_window=dict(allocation='observational',unit='readers',window='72h',observed_at=now(),notes='wrong window',
            arms=[dict(label='A',run_id=a.run_id,draft_ref='draft-a',denominator=6,outcomes=2),
                  dict(label='B',run_id=b.run_id,draft_ref='draft-b',denominator=6,outcomes=3)])
        with self.assertRaises(DomainError):
            self.command('record_trial',dict(hypothesis_id=self.hyp['id'],level='small_race',payload=invalid_window))
        self.command('record_trial', dict(hypothesis_id=self.hyp['id'], level='small_race', payload=dict(
            allocation='observational', unit='readers', window='24h', observed_at=now(), notes='两组各看同一任务，非随机',
            arms=[dict(label='A',run_id=a.run_id,draft_ref='draft-a',denominator=6,outcomes=2),
                  dict(label='B',run_id=b.run_id,draft_ref='draft-b',denominator=6,outcomes=3)])))
        return a, b

    def test_signal_and_hypothesis_are_account_bound_and_metric_matches_goal(self):
        self.assertEqual(self.signal['kind'], 'search_intent')
        self.assertEqual(self.signal['provenance'], 'user_recorded')
        self.assertEqual(self.hyp['denominator'], 'link_clicks')
        context = self.ops.context(self.owner, {'account_id':self.account,'hypothesis_id':self.hyp['id']}, 'simulation')
        self.assertEqual(context['active_hypothesis']['id'], self.hyp['id'])
        from backend.creator_context import enrich
        strategy=enrich('strategy',dict(angle='完整字幕步骤',reader='新手',candidate_angles=['步骤','对照'],cta='注册',why_account='测试'),
            {'topic':'字幕','audience':'新手','operations':context})
        self.assertEqual(strategy['content_brief']['primary_metric'],'signups')
        self.assertEqual(strategy['content_brief']['hypothesis_id'],self.hyp['id'])
        self.assertEqual(strategy['learning_refs'],[])
        with self.assertRaises(DomainError):
            self.command('create_hypothesis', dict(account_id=self.account, objective='sales', audience='新手',
                statement='另一个假设', desired_action='下单', metric='new_followers', window='24h', minimum_lift_pct=20,
                falsifier='没有增长', signal_ids=[self.signal['id']]))
        with self.assertRaises(DomainError):
            self.ops.context('someone-else', {'account_id':self.account,'hypothesis_id':self.hyp['id']}, 'simulation')

    def test_three_levels_are_ordered_and_simulation_is_never_real_attribution(self):
        with self.assertRaises(DomainError):
            self.command('record_trial', dict(hypothesis_id=self.hyp['id'], level='small_race', payload={}))
        self.record_wind_and_race()
        h = self.ops.read(self.owner)['hypotheses'][0]
        self.assertEqual(h['validations']['windtunnel']['evidence_class'], 'simulation')
        self.assertEqual(h['validations']['small_race']['causal_claim'], 'not_established')
        with self.assertRaises(DomainError):
            self.command('decide_hypothesis', dict(hypothesis_id=self.hyp['id'], verdict='supported', notes=''))
        simulated_publications = []
        with self.store.connect() as db:
            row = db.execute('SELECT payload FROM operations WHERE owner=?',(self.owner,)).fetchone()
            state = json.loads(row[0])
            h = state['hypotheses'][0]
            for idx,ref in enumerate(['draft-a','draft-b']):
                pid='sim-pub-'+str(idx)
                state['publications'].append(dict(id=pid,account_id=self.account,platform='xiaohongshu',
                    hypothesis_id=self.hyp['id'],status='SIMULATED',mode='simulation',provenance='simulation',
                    url=None,draft_ref=ref,content_hash='hash-'+ref))
                mid='sim-metric-'+str(idx);simulated_publications.append((pid,mid))
                state['metrics'].append(dict(id=mid,account_id=self.account,publication_id=pid,source_type='simulation',
                    window='24h',observed_at=now(),values={'signups':2,'impressions':100}))
            db.execute('UPDATE operations SET payload=? WHERE owner=?',(json.dumps(state,ensure_ascii=False),self.owner))
        with self.assertRaises(DomainError):
            self.command('record_trial', dict(hypothesis_id=self.hyp['id'],level='live_attribution',payload={
                'items':[dict(publication_id=p,metric_id=m) for p,m in simulated_publications],
                'evidence_method':'manual_entry','source_note':'模拟数据','observed_at':now()}))

    def test_live_stage_requires_every_race_version_and_correction_invalidates_learning(self):
        runs = self.record_wind_and_race()
        with self.store.connect() as db:
            row = db.execute('SELECT payload FROM operations WHERE owner=?',(self.owner,)).fetchone()
            state = json.loads(row[0])
            pub_metric = []
            for idx,run in enumerate(runs):
                pid='live-pub-'+str(idx);mid='live-metric-'+str(idx)
                state['publications'].append(dict(id=pid,run_id=run.run_id,draft_ref=run.drafts[0]['ref'],
                    content_hash='hash-'+run.drafts[0]['ref'],account_id=self.account,platform='xiaohongshu',
                    account='试验账号',
                    hypothesis_id=self.hyp['id'],status='MANUAL_REPORTED',mode='live',provenance='manual',
                    url='https://www.xiaohongshu.com/explore/'+str(idx),published_at=(datetime.now(timezone.utc)-timedelta(hours=25)).isoformat(),window='24h'))
                state['metrics'].append(dict(id=mid,publication_id=pid,account_id=self.account,source_type='manual',
                    window='24h',observed_at=now(),values={'signups':10+idx,'link_clicks':100}))
                pub_metric.append((pid,mid))
            db.execute('UPDATE operations SET payload=? WHERE owner=?',(json.dumps(state,ensure_ascii=False),self.owner))
        payload={'items':[dict(publication_id=p,metric_id=m) for p,m in pub_metric],
            'evidence_method':'manual_entry','source_note':'商家后台人工抄录','observed_at':now()}
        with self.assertRaises(DomainError):
            self.command('record_trial', dict(hypothesis_id=self.hyp['id'],level='live_attribution',payload={**payload,'items':payload['items'][:1]}))
        state=self.command('record_trial',dict(hypothesis_id=self.hyp['id'],level='live_attribution',payload=payload))
        self.assertEqual(state['hypotheses'][0]['validations']['live_attribution']['causal_claim'],'not_established')
        self.assertFalse(state['hypotheses'][0]['validations']['live_attribution']['meets_minimum_lift'])
        with self.assertRaises(DomainError):
            self.command('decide_hypothesis',dict(hypothesis_id=self.hyp['id'],verdict='supported',notes=''))
        state=self.command('decide_hypothesis',dict(hypothesis_id=self.hyp['id'],verdict='inconclusive',notes='样本偏少'))
        h=state['hypotheses'][0]
        self.assertEqual(h['ledger_status'],'proposed')
        self.command('hypothesis_status',dict(hypothesis_id=h['id'],status='accepted'))
        # Correct the precise 24h metric referenced by the hypothesis.
        pub=next(p for p in self.ops.read(self.owner)['publications'] if p['id']==pub_metric[0][0])
        self.command('metrics',dict(id=pub['id'],window='24h',observed_at=now(),views=1000,likes=11,saves=3,comments=2,shares=1,signups=12,link_clicks=100))
        h=next(h for h in self.ops.read(self.owner)['hypotheses'] if h['id']==self.hyp['id'])
        self.assertEqual(h['ledger_status'],'superseded')

    def reader_payload(self, with_wind=True):
        wind = self.make_run('wind-reader', workflow='windtunnel', hypothesis_id=self.hyp['id'])
        if with_wind:
            self.command('record_trial', dict(hypothesis_id=self.hyp['id'], level='windtunnel', payload={'run_id':wind.run_id,'notes':''}))
        # Existing real creations need no hypothetical-creation restart.
        a, b = self.make_run('shared-ref'), self.make_run('shared-ref')
        b.drafts[0]['content_hash']='hash-actual-variant'
        b.drafts[0]['content']['body']='先点菜单，再选导出和编码'
        self.persist_run(b)
        feedback = [dict(reader_id='reader-1',label='A',understood=False,would_act=False,answer='入口在哪里？'),
                    dict(reader_id='reader-2',label='B',understood=True,would_act=True,answer='先打开菜单再导出')]
        return dict(allocation='observational',unit='readers',window='24h',observed_at=now(),notes='each reader sees one version',
            arms=[dict(label='A',run_id=a.run_id,draft_ref='shared-ref',denominator=1,outcomes=0),
                  dict(label='B',run_id=b.run_id,draft_ref='shared-ref',denominator=1,outcomes=1)],
            reader_question='第一步做什么？',reader_feedback=feedback)

    def test_reader_feedback_is_persisted_and_computed_without_model_or_fake_growth(self):
        payload=self.reader_payload(with_wind=False)
        state=self.command('record_trial',dict(hypothesis_id=self.hyp['id'],level='small_race',payload=payload))
        race=state['hypotheses'][0]['validations']['small_race']
        self.assertNotIn('windtunnel',state['hypotheses'][0]['validations'])
        self.assertEqual(race['proxy_metric'],'stated_intent')
        self.assertEqual(race['evidence_class'],'user_recorded_reader_feedback')
        self.assertEqual(race['comprehension']['A'],{'readers':1,'understood':0})
        self.assertEqual(race['comprehension']['B'],{'readers':1,'understood':1})
        self.assertEqual(race['reader_feedback'],payload['reader_feedback'])
        self.assertEqual(race['causal_claim'],'not_established')
        self.assertIsNone(race['variant_lift_pct'])
        self.assertNotEqual(race['arms'][0]['run_id'],race['arms'][1]['run_id'])

    def test_reader_feedback_rejects_duplicate_readers_and_fabricated_totals(self):
        payload=self.reader_payload()
        import copy
        for change in ('duplicate','totals','random','missing_answer','identical','simulation'):
            invalid=copy.deepcopy(payload)
            if change=='duplicate': invalid['reader_feedback'][1]['reader_id']='reader-1'
            if change=='totals': invalid['arms'][0]['outcomes']=1
            if change=='random': invalid['allocation']='randomized'
            if change=='missing_answer': invalid['reader_feedback'][0]['answer']=''
            if change=='identical':
                run=self.store.get(invalid['arms'][1]['run_id'],self.owner)
                run.drafts[0]['content_hash']='hash-shared-ref';self.persist_run(run)
            if change=='simulation':
                run=self.store.get(invalid['arms'][0]['run_id'],self.owner)
                run.context['mode']='simulation';self.persist_run(run)
            with self.assertRaises(DomainError,msg=change):
                self.command('record_trial',dict(hypothesis_id=self.hyp['id'],level='small_race',payload=invalid))

    def test_live_attribution_rejects_changed_hash_of_exact_race_version(self):
        runs=self.record_wind_and_race()
        with self.store.connect() as db:
            state=json.loads(db.execute('SELECT payload FROM operations WHERE owner=?',(self.owner,)).fetchone()[0])
            items=[]
            for i,run in enumerate(runs):
                pid='pub-hash-'+str(i);mid='metric-hash-'+str(i);items.append(dict(publication_id=pid,metric_id=mid))
                state['publications'].append(dict(id=pid,run_id=run.run_id,draft_ref=run.drafts[0]['ref'],content_hash='changed',account_id=self.account,account='试验账号',platform=self.hyp['platform'],status='MANUAL_REPORTED',mode='live',provenance='manual',url='https://example.org/'+str(i)))
                state['metrics'].append(dict(id=mid,publication_id=pid,account_id=self.account,source_type='manual',window='24h',observed_at=now(),values={'signups':1,'link_clicks':10}))
            db.execute('UPDATE operations SET payload=? WHERE owner=?',(json.dumps(state),self.owner))
        with self.assertRaises(DomainError) as error:
            self.command('record_trial',dict(hypothesis_id=self.hyp['id'],level='live_attribution',payload=dict(items=items,evidence_method='manual_entry',source_note='actual records',observed_at=now())))
        self.assertEqual(error.exception.code,'VERSION_CONFLICT')

    def attribution_fixture(self):
        runs=self.record_wind_and_race()
        items=[]
        with self.store.connect() as db:
            state=json.loads(db.execute('SELECT payload FROM operations WHERE owner=?',(self.owner,)).fetchone()[0])
            for i, (arm, outcome, denominator) in enumerate([(0,1,10),(1,2,10),(0,80,100)]):
                run=runs[arm];pid='pub-'+str(i);mid='metric-'+str(i)
                items.append(dict(publication_id=pid,metric_id=mid))
                state['publications'].append(dict(id=pid,run_id=run.run_id,draft_ref=run.drafts[0]['ref'],content_hash=run.drafts[0]['content_hash'],account_id=self.account,platform=self.hyp['platform'],status='MANUAL_REPORTED',mode='live',provenance='manual',url='https://example.org/'+str(i),published_at=(datetime.now(timezone.utc)-timedelta(hours=25)).isoformat()))
                state['metrics'].append(dict(id=mid,publication_id=pid,account_id=self.account,source_type='manual',window='24h',observed_at=now(),values={'signups':outcome,'link_clicks':denominator}))
            db.execute('UPDATE operations SET payload=? WHERE owner=?',(json.dumps(state),self.owner))
        return dict(items=items,evidence_method='manual_entry',source_note='授权后台人工记录',observed_at=now())

    def test_attribution_aggregates_every_publication_not_just_first(self):
        payload=self.attribution_fixture()
        result=self.command('record_trial',dict(hypothesis_id=self.hyp['id'],level='live_attribution',payload=payload))['hypotheses'][0]['validations']['live_attribution']
        self.assertEqual(result['aggregates']['A']['outcome'],81)
        self.assertEqual(result['aggregates']['A']['denominator'],110)
        self.assertLess(result['variant_lift_pct'],0)
        self.assertFalse(result['meets_minimum_lift'])
        self.assertGreaterEqual(result['items'][0]['elapsed_hours'],25)
        restored=Operations(Store(self.store.path)).read(self.owner)
        self.assertEqual(restored['hypotheses'][0]['validations']['live_attribution'],result)

    def test_attribution_rejects_mislabeled_observation_window(self):
        payload=self.attribution_fixture()
        with self.store.connect() as db:
            state=json.loads(db.execute('SELECT payload FROM operations WHERE owner=?',(self.owner,)).fetchone()[0])
            state['publications'][-1]['published_at']=(datetime.now(timezone.utc)-timedelta(hours=93)).isoformat()
            db.execute('UPDATE operations SET payload=? WHERE owner=?',(json.dumps(state),self.owner))
        with self.assertRaises(DomainError) as error:
            self.command('record_trial',dict(hypothesis_id=self.hyp['id'],level='live_attribution',payload=payload))
        self.assertIn('93',str(error.exception))
        self.assertNotIn('live_attribution',self.ops.read(self.owner)['hypotheses'][0]['validations'])


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires actual PostgreSQL')
class PostgresContentTrialTests(ContentTrialTests):
    def setUp(self):
        import psycopg
        base=os.environ['TEST_DATABASE_URL'];schema='trials_'+uuid4().hex
        with psycopg.connect(base,autocommit=True) as db: db.execute('CREATE SCHEMA '+schema)
        def cleanup():
            with psycopg.connect(base,autocommit=True) as db: db.execute('DROP SCHEMA '+schema+' CASCADE')
        self.addCleanup(cleanup)
        self.database_url=base+('&' if '?' in base else '?')+'options=-csearch_path%3D'+schema
        super().setUp()


if __name__ == '__main__':
    unittest.main()

import unittest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import test_operations
from backend.analytics import AnalyticsAgent, window_quality
from backend.contracts import DomainError
from backend.planning import due_reviews


class AnalyticsTests(unittest.TestCase):
    setUp = test_operations.OperationsTests.setUp
    tearDown = test_operations.OperationsTests.tearDown
    command = test_operations.OperationsTests.command

    def sample(self):
        state = self.command('load_sample', {})
        self.account = state['accounts'][-1]
        self.metric = state['metrics'][-1]
        return state

    def plan(self):
        today = datetime.now(timezone.utc).date()
        return self.command('create_plan', dict(account_id=self.account['id'],
            week_start=(today-timedelta(days=today.weekday())).isoformat(), source_type='simulation'))['plans'][0]

    def test_baseline_references_account_window_format_and_missing_values(self):
        state = self.sample()
        report = AnalyticsAgent().run(state, self.metric, self.metric['observed_at'])
        self.assertEqual(report['status'], 'descriptive')
        self.assertEqual(report['comparisons']['saves']['current'], 24)
        self.assertEqual(report['comparisons']['saves']['baseline'], 10)
        self.assertEqual(report['comparisons']['new_followers']['current'], None)
        self.assertEqual(report['comparisons']['new_followers']['baseline'], None)
        self.assertIsNone(report['velocity'])
        self.assertEqual(report['execution']['model_calls'], 0)
        state['publications'][-1]['traffic'] = 'paid'
        report = AnalyticsAgent().run(state, self.metric, self.metric['observed_at'])
        self.assertEqual(report['status'], 'insufficient')
        self.assertIsNone(report['comparisons']['saves']['baseline'])
        self.assertTrue(report['excluded'])

    def test_early_late_and_future_baselines_never_compare(self):
        state = self.sample()
        pub = state['publications'][0]
        for hours, expected in [(1,'early'),(24,'comparable'),(31,'late')]:
            metric = {**self.metric, 'observed_at':(datetime.fromisoformat(pub['published_at'])+timedelta(hours=hours)).isoformat()}
            self.assertEqual(window_quality(pub,metric)[0],expected)
            report = AnalyticsAgent().run(state, metric, metric['observed_at'])
            if expected != 'comparable': self.assertEqual(report['status'], 'insufficient')
        state['metrics'][0]['observed_at'] = datetime.now(timezone.utc).isoformat()
        report = AnalyticsAgent().run(state, self.metric, self.metric['observed_at'])
        self.assertEqual(report['status'], 'insufficient')

    def test_baseline_correction_invalidates_analysis_memory_and_plan(self):
        self.sample()
        state = self.command('analyze', {'id':self.metric['id']})
        memory = state['memories'][0]
        self.command('memory',dict(id=memory['id'],status='accepted'))
        plan = self.plan()
        self.command('plan_status', dict(id=plan['id'],status='accepted'))
        baseline = state['metrics'][0]
        state = self.command('metrics', dict(id=baseline['publication_id'],window='24h',observed_at=baseline['observed_at'],
            views=1000,likes=30,saves=9,comments=5,shares=3))
        self.assertEqual(state['analyses'][0]['status'],'superseded')
        self.assertEqual(state['memories'][0]['status'],'superseded')
        self.assertEqual(state['plans'][0]['status'],'needs_review')
        with self.assertRaises(DomainError): self.command('plan_status',dict(id=plan['id'],status='accepted'))
        self.assertEqual(self.ops.context(self.owner,{'account_id':self.account['id']},'simulation')['memories'],[])

    def test_memory_revoke_plan_isolation_and_restart_due_jobs(self):
        self.sample(); state=self.command('analyze',{'id':self.metric['id']})
        memory=state['memories'][0]
        self.command('memory',dict(id=memory['id'],status='accepted'))
        plan=self.plan()
        self.assertEqual(plan['memory_refs'],[memory['id']])
        with self.assertRaises(DomainError): self.plan()
        with self.assertRaises(DomainError): self.command('analyze',{'id':self.metric['id']},owner='bob')
        self.assertEqual(self.ops.context(self.owner,{'account_id':self.account['id']},'live')['history'],[])
        self.assertEqual(self.ops.context(self.owner,{'account_id':self.account['id']},'live')['memories'],[])
        self.command('memory',dict(id=memory['id'],status='revoked'))
        state=self.ops.read(self.owner)
        self.assertEqual(state['plans'][0]['status'],'needs_review')
        self.assertTrue(due_reviews(state))
        from backend.operations import Operations
        from backend.store import Store
        self.assertEqual(due_reviews(state),due_reviews(Operations(Store(self.store.path)).read(self.owner)))

    def test_plan_task_date_and_account_guards(self):
        state=self.sample(); plan=self.plan(); task=plan['tasks'][0]
        payload=dict(plan_id=plan['id'],task_id=task['id'],title='重新安排选题',date=task['date'],status='done',publication_id=state['publications'][0]['id'])
        result=self.command('plan_task',payload)
        self.assertEqual(result['plans'][0]['tasks'][0]['status'],'done')
        with self.assertRaises(DomainError): self.command('plan_task',{**payload,'date':'2020-01-01'})
        with self.assertRaises(DomainError): self.command('plan_task',{**payload,'publication_id':'other'})
        self.command('plan_status',dict(id=plan['id'],status='revoked'))
        with self.assertRaises(DomainError): self.command('plan_task',payload)

    def test_metadata_changes_invalidate_dependents_and_video_metrics_are_guarded(self):
        state=self.sample();state=self.command('analyze',{'id':self.metric['id']})
        baseline=state['publications'][-1]
        state=self.command('post_metadata',dict(id=baseline['id'],format='image_text',pillar='搭配',traffic='paid'))
        self.assertEqual(state['analyses'][0]['status'],'superseded')
        self.assertEqual(state['memories'][0]['status'],'superseded')
        with self.assertRaises(DomainError):
            self.command('metrics',dict(id=self.metric['publication_id'],window='24h',observed_at=self.metric['observed_at'],
                views=1000,likes=30,saves=20,comments=5,shares=3,completed_plays=800))

    def test_one_memory_does_not_fill_every_weekly_slot(self):
        self.sample();state=self.command('analyze',{'id':self.metric['id']})
        memory=state['memories'][0];self.command('memory',dict(id=memory['id'],status='accepted'))
        plan=self.plan()
        self.assertEqual(sum(t['memory_ref'] is not None for t in plan['tasks']),1)
        self.assertEqual(len({t['title'] for t in plan['tasks']}),3)

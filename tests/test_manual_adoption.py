"""Human adoption remains distinct from reviewer approval and publication approval."""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from backend.contracts import DomainError
from backend.provider import Config
from backend.service import Service
from backend.store import Store


class ManualAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'test.sqlite')
        self.prepare()

    def prepare(self):
        self.service = Service(self.store, Config())
        self.owner = 'alice'
        self.run = self.service.create(self.owner, dict(topic='测试', audience='读者', tone='真实', material='素材', scenario='revision'))
        for _ in range(8):
            if self.run.get('review'): break
            self.act('next', {})
        self.assertEqual(self.run['review']['decision'], 'revision_required')

    def act(self, action, payload, **overrides):
        data = dict(action=action, payload=payload, version=self.run['status_version'], key=str(uuid4()))
        data.update(overrides)
        self.run = self.service.action(self.owner, self.run['run_id'], data)
        return self.run

    def payload(self):
        draft = self.run['drafts'][-1]
        return dict(draft_ref=draft['ref'], content_hash=draft['content_hash'], acknowledge=True)

    def test_adoption_preserves_review_and_issues_idempotently(self):
        review = copy.deepcopy(self.run['review'])
        payload = self.payload(); version = self.run['status_version']; key = str(uuid4())
        self.act('adopt_manual', payload, version=version, key=key)
        self.assertEqual(self.run['run_status'], 'SUCCEEDED')
        self.assertEqual(self.run['review'], review)
        self.assertEqual(self.run['acceptance']['mode'], 'manual_override')
        self.assertEqual(self.run['acceptance']['acknowledged_issues'], review['issues'])
        self.assertEqual(self.act('adopt_manual', payload, version=version, key=key)['status_version'], version + 1)
        self.assertIn('用户人工采用', self.service.export(self.owner, self.run['run_id']))
        self.assertIn('未通过 AI 审核', self.service.export(self.owner, self.run['run_id']))
        reloaded = Store(self.store.path).get(self.run['run_id'], self.owner)
        self.assertEqual(reloaded.acceptance, self.run['acceptance'])

    def test_exact_version_ack_owner_and_terminal_guards(self):
        for changes in ({'acknowledge':False}, {'draft_ref':'stale'}, {'content_hash':'stale'}):
            with self.assertRaises(DomainError): self.act('adopt_manual', {**self.payload(), **changes})
        with self.assertRaises(DomainError): self.act('adopt_manual', self.payload(), version=0)
        with self.assertRaises(DomainError):
            self.service.action('bob', self.run['run_id'], dict(action='adopt_manual',payload=self.payload(),version=self.run['status_version'],key=str(uuid4())))
        self.act('cancel', {})
        with self.assertRaises(DomainError): self.act('adopt_manual', self.payload())

    def test_revision_limit_edit_then_adopt_without_model_or_review(self):
        run = self.store.get(self.run['run_id'], self.owner)
        run.run_status = 'WAITING_USER'; run.wait_reason = 'revision_limit'; run.iteration = 2
        from dataclasses import asdict
        import json
        with self.store.connect() as db:
            db.execute('UPDATE runs SET payload=? WHERE id=?', (json.dumps(asdict(run)),run.run_id))
        self.run = self.service.view(run)
        old_review = copy.deepcopy(run.review)
        content = copy.deepcopy(self.run['drafts'][-1]['content']); content['body'] = '人工修订的正文'
        self.act('edit', content)
        self.assertIsNone(self.run['review'])
        self.assertIn('adopt_manual', self.run['allowed_actions'])
        self.act('adopt_manual', self.payload())
        self.assertIsNone(self.run['acceptance']['review_ref'])
        self.assertEqual(self.run['acceptance']['acknowledged_issues'],old_review['issues'])
        self.assertEqual(self.run['usage']['model_calls'], 0)
        ops = self.service.operations
        def operation(action, payload):
            return ops.command(self.owner, dict(action=action,payload=payload,version=ops.read(self.owner)['version'],key=str(uuid4())))
        state = operation('prepare',dict(run_id=run.run_id,draft_ref=self.run['accepted_ref']))
        pub = state['publications'][0]
        self.assertEqual(pub['status'],'AWAITING_APPROVAL')
        self.assertEqual(pub['acceptance']['mode'],'manual_override')
        self.assertIsNone(pub['review_ref'])
        self.assertEqual(operation('approve',dict(id=pub['id']))['publications'][0]['status'],'APPROVED')

    def test_active_job_and_live_step_reject_adoption(self):
        with self.store.connect() as db:
            db.execute("INSERT INTO live_steps(run_id,key,version,state) VALUES(?,?,?,?)",(self.run['run_id'],'active',self.run['status_version'],'running'))
        with self.assertRaises(DomainError) as caught: self.act('adopt_manual',self.payload())
        self.assertEqual(caught.exception.code,'JOB_ACTIVE')

    def test_background_activity_rejects_then_paused_adoption_completes_job(self):
        import json
        from backend.jobs import graph_policy
        with self.store.connect() as db:
            db.execute("INSERT INTO runtime_jobs(id,run_id,owner,status,updated,thread_id,policy) VALUES(?,?,?,?,?,?,?)",
                       (str(uuid4()),self.run['run_id'],self.owner,'running',0,str(uuid4()),json.dumps(graph_policy(self.store.get(self.run['run_id'],self.owner)))))
        self.assertNotIn('adopt_manual',self.service.view(self.store.get(self.run['run_id'],self.owner))['allowed_actions'])
        with self.assertRaises(DomainError) as caught: self.act('adopt_manual',self.payload())
        self.assertEqual(caught.exception.code,'JOB_ACTIVE')
        with self.store.connect() as db:
            db.execute("UPDATE runtime_jobs SET status='paused' WHERE run_id=?",(self.run['run_id'],))
        self.act('adopt_manual',self.payload())
        self.assertEqual(self.run['background']['status'],'done')

    def test_approved_review_keeps_normal_confirmation(self):
        self.act('next', {})
        self.act('next', {})
        self.assertEqual(self.run['review']['decision'], 'approved')
        self.assertNotIn('adopt_manual', self.run['allowed_actions'])
        with self.assertRaises(DomainError):self.act('adopt_manual', self.payload())
        self.act('accept', dict(draft_ref=self.run['drafts'][-1]['ref'], review_ref=self.run['review']['ref']))
        self.assertEqual(self.run['acceptance']['mode'],'reviewed')

    def test_no_draft_or_stale_snapshot_or_failed_cannot_adopt(self):
        from backend.workflow import Run
        empty=Run('alice','s',run_status='WAITING_USER',wait_reason='missing_material')
        self.assertFalse(empty.can_manual_adopt())
        run=self.store.get(self.run['run_id'],self.owner)
        run.run_status='FAILED'
        self.assertFalse(run.can_manual_adopt())
        run.run_status='WAITING_USER';run.wait_reason='missing_material'
        self.assertTrue(run.can_manual_adopt())
        run.snapshot_id='another'
        self.assertFalse(run.can_manual_adopt())


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires actual PostgreSQL')
class PostgresManualAdoptionTests(ManualAdoptionTests):
    def setUp(self):
        import psycopg
        self.schema='youji_manual_test_'+uuid4().hex
        self.base=os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base,autocommit=True) as db:
            db.execute('CREATE SCHEMA '+self.schema)
        self.addCleanup(self.drop_schema)
        target=self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema
        self.store=Store(target)
        self.prepare()

    def drop_schema(self):
        import psycopg
        with psycopg.connect(self.base,autocommit=True) as db:
            db.execute('DROP SCHEMA '+self.schema+' CASCADE')

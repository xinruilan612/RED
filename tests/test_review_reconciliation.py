"""Free review reconciliation preserves evidence, user confirmation and paid ledger."""
import copy
import json
import os
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from backend.contracts import DomainError
from backend.live import schema
from backend.provider import Config
from backend.service import Service
from backend.store import Store


class ReviewReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'reconcile.sqlite');self.prepare()

    def prepare(self):
        class NoTransport:
            def complete(self,*args):raise AssertionError('must not call model')
        self.service=Service(self.store,Config('fixture-never-sent'),NoTransport())
        self.owner='reconcile-fixture'
        created=self.service.create(self.owner,dict(topic='资料步骤',audience='测试读者',tone='清楚',
            material='公开资料测试文字。',allow_hypothesis=True,mode='live'))
        self.run=self.store.get(created['run_id'],self.owner)
        self.run.start();self.run.current_stage='content'
        self.run.branches={'research':{'data':{'core_gap':False}}}
        self.run.draft(dict(selected_title='资料步骤',body='当前测试正文',cta='请核对条件',tags=[]))
        draft=self.run.drafts[-1]
        report=schema('review')
        report.update(ref='original-review@1',draft_ref=draft['ref'],snapshot_id=self.run.snapshot_id,
            content_hash=draft['content_hash'],policy_ref='text-review@1',mode='live',
            decision='revision_required',next_action='revise',claim_map=[],previous_issue_results=[],
            human_questions=[],issues=[dict(issue_id='optional',severity='minor',state='open',location='body',
                excerpt='当前测试正文',reason='可选风格优化',suggestion='可保留当前正文')])
        for check in report['checks']:check.update(result='pass',basis='本项已核验')
        self.run.review=report;self.run.reviews=[copy.deepcopy(report)]
        self.run.current_stage='content';self.run.iteration=2
        self.run.run_status='WAITING_USER';self.run.wait_reason='revision_limit';self.save()

    def save(self):
        with self.store.connect() as db:
            db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(asdict(self.run),ensure_ascii=False),self.run.run_id))

    def command(self,**kwargs):
        data=dict(action='reconcile_review',version=self.run.status_version,key='reconcile-key',payload={})
        data.update(kwargs)
        return self.service.action(self.owner,self.run.run_id,data)

    def test_reconcile_after_limit_preserves_history_no_charge_waits_for_user(self):
        before=copy.deepcopy(self.run.review)
        with self.store.connect() as db:
            db.execute('INSERT INTO live_calls(id,run_id,agent,stage,reserved,actual,state,response_json) VALUES(?,?,?,?,?,?,?,?)',
                ('settled',self.run.run_id,'reviewer','review',17,9,'validated',json.dumps(before)))
        self.assertTrue(self.service.view(self.run)['review_reconciliation']['available'])
        result=self.command()
        run=self.store.get(self.run.run_id,self.owner)
        self.assertEqual((run.run_status,run.wait_reason),('WAITING_USER','final_confirmation'))
        self.assertIsNone(run.acceptance);self.assertIsNone(run.accepted_ref)
        self.assertEqual(run.reviews[0],before);self.assertEqual(len(run.reviews),2)
        self.assertEqual(run.review['reconciled_from'],before['ref'])
        self.assertNotEqual(run.review['ref'],before['ref'])
        self.assertEqual(run.iteration,2);self.assertEqual(run.node_runs[-1]['model_calls'],0)
        self.assertEqual(result['usage']['model_calls'],1)
        self.assertEqual(result['usage']['tokens'],9)
        with self.store.connect() as db:
            row=db.execute('SELECT actual,state,response_json FROM live_calls WHERE id=?',('settled',)).fetchone()
        self.assertEqual((row[0],row[1],json.loads(row[2])),(9,'validated',before))
        self.assertIn('accept',result['allowed_actions'])
        self.assertFalse(result['review_reconciliation']['available'])
        self.command()  # Same version/key is an idempotent replay.
        self.assertEqual(asdict(self.store.get(self.run.run_id,self.owner)),asdict(run))
        with self.assertRaises(DomainError):self.command(version=run.status_version)

    def test_no_reconciliation_for_blocking_failed_unknown_or_human(self):
        original=copy.deepcopy(self.run.review)
        for mutate in (lambda r:r['issues'][0].update(severity='major'),
                       lambda r:r['checks'][0].update(result='fail'),
                       lambda r:r['checks'][0].update(result='unknown'),
                       lambda r:r.update(human_questions=['请补料'])):
            self.run.review=copy.deepcopy(original);mutate(self.run.review)
            self.run.reviews=[copy.deepcopy(self.run.review)];self.save()
            self.assertFalse(self.service.view(self.run)['review_reconciliation']['available'])
            with self.assertRaises(DomainError):self.command()

    def test_stale_version_owner_snapshot_and_terminal_guards(self):
        with self.assertRaises(DomainError):self.command(version=42)
        with self.assertRaises(DomainError):
            self.service.action('other-owner',self.run.run_id,dict(action='reconcile_review',version=0,key='x',payload={}))
        for status in ('SUCCEEDED','FAILED','CANCELLED'):
            self.run.run_status=status;self.save()
            with self.assertRaises(DomainError):self.command()
        self.run.run_status='WAITING_USER';self.run.snapshot_id='stale';self.save()
        with self.assertRaises(DomainError):self.command()

    def test_unsettled_usage_and_active_step_block_without_mutation(self):
        with self.store.connect() as db:
            db.execute('INSERT INTO live_calls(id,run_id,agent,stage,reserved,actual,state) VALUES(?,?,?,?,?,?,?)',
                ('pending',self.run.run_id,'reviewer','review',17,None,'unknown'))
        with self.assertRaises(DomainError):self.command()
        self.assertEqual(len(self.store.get(self.run.run_id,self.owner).reviews),1)
        with self.store.connect() as db:
            db.execute('DELETE FROM live_calls WHERE id=?',('pending',))
            db.execute('INSERT INTO live_steps(run_id,version,key,state) VALUES(?,?,?,?)',(self.run.run_id,0,'step','running'))
        with self.assertRaises(DomainError):self.command()


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'requires actual PostgreSQL')
class PostgresReviewReconciliationTests(ReviewReconciliationTests):
    def setUp(self):
        import psycopg
        self.schema='youji_reconcile_'+uuid4().hex;self.base=os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('CREATE SCHEMA '+self.schema)
        self.addCleanup(self.drop_schema)
        self.store=Store(self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema)
        self.prepare()

    def drop_schema(self):
        import psycopg
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('DROP SCHEMA '+self.schema+' CASCADE')

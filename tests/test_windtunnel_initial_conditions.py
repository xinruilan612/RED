"""Manual recovery after an empty model question list, using fixture calls only."""
import copy
import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from backend.contracts import DomainError
from backend.store import Store
from backend.worker import Worker
from backend import windtunnel as wt
from tests import test_windtunnel_runtime as helpers


class InitialConditionsTests(unittest.TestCase):
    prepare=helpers.WindtunnelRuntimeTests.prepare
    value=helpers.WindtunnelRuntimeTests.value
    action=helpers.WindtunnelRuntimeTests.action
    start=helpers.WindtunnelRuntimeTests.start
    work=helpers.WindtunnelRuntimeTests.work
    confirm=helpers.WindtunnelRuntimeTests.confirm
    job=helpers.WindtunnelRuntimeTests.job

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'manual-questions.sqlite')
        self.setup_empty_sources()

    def setup_empty_sources(self):
        self.prepare()
        self.action('cancel')
        self.input['materials']=[]
        self.run_id=self.service.create(self.owner,self.input)['run_id']
        self.assertEqual(self.value().windtunnel['sources'],[])

    def tearDown(self):self.tmp.cleanup()

    def question(self,identity='question-1'):
        return dict(id=identity,question='读完后第一步做什么？',scene='第一次使用工具',source_ids=[],origin='author')

    def persist(self,run):
        import json
        with self.store.connect() as db:
            db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(asdict(run),ensure_ascii=False),run.run_id))

    def command(self,payload=None,owner=None,version=None,key=None):
        return self.service.action(owner or self.owner,self.run_id,dict(action='set_initial_conditions',
            version=self.value().status_version if version is None else version,key=key or uuid4().hex,
            payload={'conditions':[self.question()]} if payload is None else payload))

    def test_owner_version_and_idempotency_are_enforced(self):
        original=self.value()
        with self.assertRaises(DomainError):self.command(owner='another-owner')
        with self.assertRaises(DomainError) as error:self.command(version=original.status_version+1)
        self.assertEqual(error.exception.code,'VERSION_CONFLICT')
        self.assertEqual(asdict(self.value()),asdict(original))
        key=uuid4().hex
        first=self.command(version=original.status_version,key=key)
        replay=self.command(version=original.status_version,key=key)
        self.assertEqual(first,replay)
        self.assertEqual(len(self.value().windtunnel['condition_sets']),1)
        with self.assertRaises(DomainError) as error:
            self.command(payload={'conditions':[self.question('another')]},version=original.status_version,key=key)
        self.assertEqual(error.exception.code,'IDEMPOTENCY_CONFLICT')

    def test_only_unfinished_initial_stage_can_be_repaired(self):
        original=self.value()
        for status in ('FAILED','CANCELLED','EXPIRED','SUCCEEDED'):
            with self.subTest(status=status):
                candidate=copy.deepcopy(original);candidate.run_status=status;self.persist(candidate)
                with self.assertRaises(DomainError):self.command()
                self.assertEqual(self.value().windtunnel['condition_sets'],[])
        candidate=copy.deepcopy(original);candidate.current_stage='wt_read';self.persist(candidate)
        with self.assertRaises(DomainError):self.command()
        # A run awaiting input can also recover the absent initial question list.
        candidate=copy.deepcopy(original);candidate.run_status='WAITING_USER';self.persist(candidate)
        self.command()
        self.assertEqual(self.value().wait_reason,'wt_confirm_conditions')
        self.assertFalse(wt.conditions(self.value())['confirmed'])

    def test_question_count_ids_and_author_provenance_are_validated(self):
        baseline=self.value()
        for questions in ([],[self.question(str(i)) for i in range(13)], [self.question(),self.question()]):
            with self.subTest(count=len(questions)):
                with self.assertRaises(DomainError):self.command({'conditions':questions})
                self.assertEqual(asdict(self.value()),asdict(baseline))
        for question in (dict(self.question(),origin='feedback'),dict(self.question(),source_ids=['unavailable-feedback'])):
            with self.assertRaises(DomainError):self.command({'conditions':[question]})
            self.assertEqual(asdict(self.value()),asdict(baseline))
        self.command({'conditions':[self.question(str(i)) for i in range(12)]})
        self.assertEqual(len(wt.conditions(self.value())['conditions']),12)
        self.assertTrue(all(c['origin']=='author' and c['source_ids']==[] for c in wt.conditions(self.value())['conditions']))

    def test_existing_confirmed_questions_cannot_be_overwritten(self):
        self.command();self.confirm()
        saved=copy.deepcopy(self.value().windtunnel['condition_sets'])
        with self.assertRaises(DomainError):self.command({'conditions':[self.question('overwrite')]})
        self.assertEqual(self.value().windtunnel['condition_sets'],saved)

    def test_active_jobs_hide_and_reject_manual_repair(self):
        self.start()
        for status in ('queued','running','pausing'):
            with self.subTest(status=status):
                with self.store.connect() as db:
                    db.execute('UPDATE runtime_jobs SET status=? WHERE run_id=?',(status,self.run_id))
                before=self.value()
                self.assertNotIn('set_initial_conditions',self.service.view(before)['allowed_actions'])
                with self.assertRaises(DomainError):self.command()
                self.assertEqual(asdict(self.value()),asdict(before))

    def test_unknown_paid_usage_cannot_be_bypassed_by_manual_questions(self):
        for state,actual in (('calling',None),('calling',100),('received',None),('failed',None)):
            with self.subTest(state=state,actual=actual):
                call_id=uuid4().hex
                with self.store.connect() as db:
                    db.execute('INSERT INTO live_calls(id,run_id,agent,stage,reserved,state,actual) VALUES(?,?,?,?,?,?,?)',
                        (call_id,self.run_id,'audience','wt_conditions',3000,state,actual))
                before=self.value()
                self.assertNotIn('set_initial_conditions',self.service.view(before)['allowed_actions'])
                with self.assertRaises(DomainError):self.command()
                self.assertEqual(asdict(self.value()),asdict(before))
                self.assertEqual(self.fixture.calls,[])
                with self.store.connect() as db:
                    self.assertEqual(db.execute('SELECT state,actual FROM live_calls WHERE id=?',(call_id,)).fetchone(),(state,actual))
                    db.execute('DELETE FROM live_calls WHERE id=?',(call_id,))

    def test_blocked_empty_model_response_recovers_without_recharging_question_generation(self):
        def complete(messages):
            run=self.value();self.fixture.calls.append((run.current_stage,messages))
            return ({'conditions':[]} if run.current_stage=='wt_conditions' else wt.simulate(run,run.current_stage)),100
        self.fixture.complete=complete
        self.work()
        self.assertEqual(self.job()['status'],'blocked')
        self.assertEqual(self.value().windtunnel['condition_sets'],[])
        old_snapshot=self.value().snapshot_id
        with self.store.connect() as db:
            old_thread=db.execute('SELECT thread_id FROM runtime_jobs WHERE run_id=?',(self.run_id,)).fetchone()[0]
            before_calls=db.execute("SELECT COUNT(*) FROM live_calls WHERE run_id=? AND stage='wt_conditions'",(self.run_id,)).fetchone()[0]
        self.assertEqual(before_calls,1)
        self.assertIn('set_initial_conditions',self.service.view(self.value())['allowed_actions'])
        self.command()
        self.assertNotEqual(self.value().snapshot_id,old_snapshot)
        self.assertEqual(wt.conditions(self.value())['provenance'],{'method':'manual_author','model_calls':0})
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT state FROM live_calls WHERE run_id=? AND stage='wt_conditions'",(self.run_id,)).fetchone()[0],'invalid')
        self.assertEqual(self.job()['status'],'waiting')
        with self.store.connect() as db:
            self.assertNotEqual(db.execute('SELECT thread_id FROM runtime_jobs WHERE run_id=?',(self.run_id,)).fetchone()[0],old_thread)
        self.confirm();self.work()
        self.assertEqual(self.value().wait_reason,'wt_report',self.job())
        self.assertEqual(len(self.value().windtunnel['reports']),1)
        self.assertEqual([stage for stage,_ in self.fixture.calls],['wt_conditions','wt_read','wt_verify'])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM live_calls WHERE run_id=? AND stage='wt_conditions'",(self.run_id,)).fetchone()[0],before_calls)
        self.assertEqual(self.value().windtunnel['reports'][0]['mode'],'live')


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'requires actual PostgreSQL')
class PostgresInitialConditionsTests(InitialConditionsTests):
    def setUp(self):
        import psycopg
        self.tmp=tempfile.TemporaryDirectory();self.schema='youji_initial_questions_'+uuid4().hex
        self.base=os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('CREATE SCHEMA '+self.schema)
        target=self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema
        self.store=Store(target);self.setup_empty_sources()

    def tearDown(self):
        import psycopg
        super().tearDown()
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('DROP SCHEMA '+self.schema+' CASCADE')

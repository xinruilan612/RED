"""Review-call exhaustion blocks before queuing; fixtures never call a provider."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from backend.contracts import DomainError
from backend.live import messages_for, schema
from backend.model_router import Route, review_execution, stage_attempt_count
from backend.provider import Config
from backend.service import Service
from backend.store import Store
from backend.workflow import digest


class NoTransport:
    def complete(self, _messages):
        raise AssertionError('preflight must never call a provider')


class ReviewPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'preflight.sqlite')
        self.prepare()

    def prepare(self):
        self.owner='preflight-fixture'
        self.service=Service(self.store,Config('fixture-never-sent'),NoTransport())
        created=self.service.create(self.owner,dict(topic='资料步骤',audience='测试读者',tone='清楚',
            material='公开资料测试文字。',allow_hypothesis=True,mode='live'))
        self.run=self.store.get(created['run_id'],self.owner)
        self.run.start();self.run.current_stage='content'
        self.run.draft(dict(selected_title='资料步骤',body='当前测试正文',cta='请核对条件',tags=[]))
        self.save()

    def save(self):
        with self.store.connect() as db:
            db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(asdict(self.run),ensure_ascii=False),self.run.run_id))

    def seed(self,count,*,state='validated',actual=9,replay=False):
        messages,_=messages_for(self.run,'review')
        route=Route(**self.run.context['model_policy']['routes']['review'])
        input_hash=digest({'messages':messages,'snapshot':self.run.snapshot_id,'route':asdict(route)})
        with self.store.connect() as db:
            for i in range(count):
                call_id=str(uuid4())
                db.execute('INSERT INTO live_calls(id,run_id,agent,stage,reserved,actual,state,response_json) VALUES(?,?,?,?,?,?,?,?)',
                    (call_id,self.run.run_id,'reviewer','review',17,actual,state,json.dumps(schema('review'))))
                db.execute('INSERT INTO model_audit(call_id,run_id,agent,stage,provider,model,route_version,prompt_version,input_hash,sources,snapshot_id,started,rate,outcome) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (call_id,self.run.run_id,'reviewer','review',route.provider,route.model,self.run.context['model_policy']['version'],self.run.context['model_policy']['prompt_version'],input_hash if replay and i==count-1 else 'other-input-'+call_id,'[]',self.run.snapshot_id,0,route.rate,state))
        return messages

    def command(self,action):
        return self.service.background(self.owner,self.run.run_id,
            dict(action=action,version=self.run.status_version,key=str(uuid4())))

    def test_public_quota_counts_calls_not_revision_rounds_and_keeps_manual_actions(self):
        self.seed(3);self.assertEqual(self.run.iteration,0)
        viewed=self.service.view(self.run);quota=viewed['review_execution']
        self.assertEqual((quota['used'],quota['limit'],quota['remaining']),(3,3,0))
        self.assertTrue(quota['blocked']);self.assertNotIn('next',viewed['allowed_actions'])
        self.assertIn('edit',viewed['allowed_actions']);self.assertIn('adopt_manual',viewed['allowed_actions'])
        self.assertNotIn('accept',viewed['allowed_actions']);self.assertIn('复审次数已用完',quota['message'])
        self.assertEqual(viewed['usage']['model_calls'],3)

    def test_legacy_revision_limit_wait_also_explains_exhausted_unreviewed_draft(self):
        self.seed(3);self.run.run_status='WAITING_USER';self.run.wait_reason='revision_limit';self.save()
        viewed=self.service.view(self.run)
        self.assertTrue(viewed['review_execution']['blocked'])
        self.assertIn('3/3',viewed['review_execution']['message'])
        self.assertIn('adopt_manual',viewed['allowed_actions']);self.assertNotIn('next',viewed['allowed_actions'])

    def test_start_and_step_reject_before_job_command_version_or_ledger_changes(self):
        self.seed(3)
        before=asdict(self.store.get(self.run.run_id,self.owner))
        for action in ('start','step'):
            with self.subTest(action=action),self.assertRaises(DomainError) as error:
                self.command(action)
            self.assertEqual(error.exception.code,'STAGE_ATTEMPT_LIMIT')
        self.assertEqual(asdict(self.store.get(self.run.run_id,self.owner)),before)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM runtime_jobs').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM runtime_commands').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM live_calls').fetchone()[0],3)

    def test_sync_next_also_rejects_before_claiming_a_step(self):
        self.seed(3)
        with self.assertRaises(DomainError) as error:
            self.service.action(self.owner,self.run.run_id,dict(action='next',payload={},version=self.run.status_version,key=str(uuid4())))
        self.assertEqual(error.exception.code,'STAGE_ATTEMPT_LIMIT')
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM live_steps').fetchone()[0],0)

    def test_remaining_review_slot_is_not_hidden_or_blocked(self):
        self.seed(2)
        viewed=self.service.view(self.run)
        self.assertEqual(viewed['review_execution']['remaining'],1)
        self.assertFalse(viewed['review_execution']['blocked']);self.assertIn('next',viewed['allowed_actions'])
        self.assertEqual(self.command('step')['background']['status'],'queued')

    def test_inherited_failed_invalid_and_received_calls_all_count(self):
        for state in ('failed','invalid','received'):self.seed(1,state=state)
        self.run.run_status='FAILED';self.save()
        child=self.service.executor.recover(self.run.run_id,self.owner,self.run.status_version)
        viewed=self.service.view(child)
        self.assertEqual(viewed['review_execution']['used'],3)
        self.assertTrue(viewed['review_execution']['blocked'])
        self.assertTrue(all(call['inherited'] for call in viewed['calls']))
        with self.assertRaises(DomainError) as error:
            self.service.background(self.owner,child.run_id,dict(action='start',version=child.status_version,key=str(uuid4())))
        self.assertEqual(error.exception.code,'STAGE_ATTEMPT_LIMIT')

    def test_matching_received_response_at_limit_replays_without_a_new_call(self):
        messages=self.seed(3,state='received',replay=True)
        with self.store.connect() as db:quota=review_execution(db,self.run)
        self.assertTrue(quota['replayable']);self.assertFalse(quota['blocked'])
        before=self.service.executor.public(self.run)['usage']
        value,tokens,_=self.service.executor.calls.invoke(self.run,'reviewer','review',messages,lambda _db:None,reuse=True)
        self.assertEqual(value,schema('review'));self.assertEqual(tokens,9)
        self.assertEqual(self.service.executor.public(self.run)['usage'],before)
        self.assertEqual(self.command('start')['background']['status'],'queued')

    def test_unknown_or_invalid_cached_response_cannot_bypass_limit(self):
        for state,actual in (('calling',None),('invalid',9)):
            with self.subTest(state=state):
                with self.store.connect() as db:
                    db.execute('DELETE FROM model_audit');db.execute('DELETE FROM live_calls')
                self.seed(3,state=state,actual=actual,replay=True)
                viewed=self.service.view(self.run)
                self.assertFalse(viewed['review_execution']['replayable'])
                self.assertTrue(viewed['review_execution']['blocked'])
                with self.assertRaises(DomainError) as error:self.command('step')
                self.assertEqual(error.exception.code,'STAGE_ATTEMPT_LIMIT')

    def test_body_and_revise_still_share_the_original_stage_counter(self):
        with self.store.connect() as db:
            for stage in ('body','revise'):
                db.execute('INSERT INTO live_calls(id,run_id,agent,stage,reserved,state) VALUES(?,?,?,?,?,?)',
                    (str(uuid4()),self.run.run_id,'content',stage,17,'failed'))
            for stage in ('body','revise'):
                self.assertEqual(stage_attempt_count(db,self.run.run_id,'content',stage),2)
            self.assertEqual(stage_attempt_count(db,self.run.run_id,'reviewer','review'),0)

    def test_new_paid_revision_is_rejected_before_reservation_when_no_review_slot_remains(self):
        self.seed(3)
        self.run.current_stage='content';self.run.review={'decision':'revision_required','issues':[]}
        messages,_=messages_for(self.run,'revise')
        with self.assertRaises(DomainError) as error:
            self.service.executor.calls.invoke(self.run,'content','revise',messages,lambda _db:None,reuse=True)
        self.assertEqual(error.exception.code,'STAGE_ATTEMPT_LIMIT')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM live_calls').fetchone()[0],3)
            self.assertEqual(stage_attempt_count(db,self.run.run_id,'content','revise'),0)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'requires actual PostgreSQL')
class PostgresReviewPreflightTests(ReviewPreflightTests):
    def setUp(self):
        import psycopg
        self.schema='youji_review_preflight_'+uuid4().hex
        self.base=os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('CREATE SCHEMA '+self.schema)
        self.addCleanup(self.drop_schema)
        target=self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema
        self.store=Store(target)
        self.prepare()

    def drop_schema(self):
        import psycopg
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('DROP SCHEMA '+self.schema+' CASCADE')

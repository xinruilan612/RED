"""Offline acceptance for settled review recovery and transactional fences."""
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from backend.contracts import DomainError
from backend.provider import Config
from backend.service import Service
from backend.store import Store
from backend.worker import Worker
from backend.workflow import Run
from test_live_provider import FixtureModel

class ReviewRuntimeHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'handoff.sqlite')
        self.model=FixtureModel()
        self.service=Service(self.store,Config('offline-fixture-only'),self.model)
        self.owner='offline-review-owner'
        self.run_id=self.service.create(self.owner,dict(topic='公共资料测试',audience='读者',tone='清楚',material='这是一份公开资料的测试摘要。',allow_hypothesis=True,mode='live',web_research={'enabled':False,'queries':[]}))['run_id']
    def tearDown(self):self.temp.cleanup()
    def run_value(self):return self.store.get(self.run_id,self.owner)
    def start(self):
        return self.service.background(self.owner,self.run_id,dict(action='start',version=self.run_value().status_version,key=str(uuid4())))
    def job(self):return self.service.jobs.public(self.run_id,self.owner)
    def requeue_crashed_worker(self):
        # Simulate durable queue discovery after a process died, without the
        # browser command (which intentionally rejects pending human work).
        with self.store.connect() as db:
            db.execute("UPDATE runtime_jobs SET status='queued',error=NULL WHERE run_id=?",(self.run_id,))
    def install_review(self, transform):
        base=self.model.complete
        def complete(messages):
            raw,tokens=base(messages)
            return (transform(raw) if self.model.calls[-1]=='review' else raw),tokens
        self.model.complete=complete
    def audit(self):
        with self.store.connect() as db:
            return db.execute("SELECT c.response_json,c.actual,c.state,a.outcome,c.error FROM live_calls c JOIN model_audit a ON a.call_id=c.id WHERE c.run_id=? AND c.stage='review'",(self.run_id,)).fetchone()
    def assert_handoff(self, expected_raw=None):
        run=self.run_value()
        self.assertEqual(self.job()['status'],'waiting',self.job())
        self.assertEqual(run.run_status,'WAITING_USER')
        self.assertEqual(run.review['decision'],'needs_human')
        self.assertEqual(run.review['draft_ref'],run.drafts[-1]['ref'])
        self.assertEqual(run.review['content_hash'],run.drafts[-1]['content_hash'])
        self.assertTrue(run.review['human_questions'])
        self.assertTrue(all(c['result']=='unknown' for c in run.review['checks']))
        raw,tokens,state,outcome,error=self.audit()
        self.assertEqual((tokens,state,outcome),(120,'invalid','invalid'))
        self.assertTrue(error)
        if expected_raw is not None:self.assertEqual(json.loads(raw),expected_raw)
        self.assertEqual(self.model.calls.count('review'),1)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runtime_nodes WHERE run_id=? AND stage='review'",(self.run_id,)).fetchone()[0],1)
        return run
    def test_missing_review_fields_become_human_handoff(self):
        self.install_review(lambda raw:{})
        self.start();Worker(self.service).once();self.assert_handoff({})
    def test_non_object_response_is_preserved(self):
        self.install_review(lambda raw:['unexpected review'])
        self.start();Worker(self.service).once();self.assert_handoff(['unexpected review'])
    def test_invalid_approved_decision_becomes_handoff(self):
        def fail(raw):raw['checks'][0]['result']='fail';return raw
        self.install_review(fail)
        self.start();Worker(self.service).once();self.assert_handoff()
    def test_reviewed_second_layer_failure_retains_invalid_audit(self):
        original=Run.reviewed
        def reject_once(run,report,gates,fail_on_limit=False):
            if not report.get('recovery_kind'):raise DomainError('MODEL_OUTPUT_INVALID','second layer review schema failure')
            return original(run,report,gates,fail_on_limit=fail_on_limit)
        self.start()
        with patch.object(Run,'reviewed',reject_once):Worker(self.service).once()
        self.assert_handoff()
    def test_stored_invalid_response_replays_without_new_request(self):
        self.install_review(lambda raw:{})
        def crash(point,stage):
            if point=='after_response' and stage=='review':raise RuntimeError('offline crash')
        self.start();Worker(self.service,fault=crash).once()
        self.assertEqual(self.job()['status'],'blocked')
        with self.store.connect() as db:
            db.execute("UPDATE live_calls SET state='invalid',error='legacy schema error' WHERE run_id=? AND stage='review'",(self.run_id,))
            db.execute("UPDATE model_audit SET outcome='invalid' WHERE run_id=? AND stage='review'",(self.run_id,))
        self.requeue_crashed_worker();Worker(self.service).once();self.assert_handoff({})
    def test_crash_after_commit_does_not_duplicate_review_or_charge(self):
        self.install_review(lambda raw:{})
        def crash(point,stage):
            if point=='after_commit' and stage=='review':raise RuntimeError('offline crash')
        self.start();Worker(self.service,fault=crash).once()
        self.assertEqual(self.run_value().run_status,'WAITING_USER')
        self.requeue_crashed_worker();Worker(self.service).once();self.assert_handoff({})
        self.assertEqual(len(self.run_value().reviews),1)
    def test_snapshot_change_blocks_recovery(self):
        self.install_review(lambda raw:{})
        def change(point,stage):
            if point=='after_response' and stage=='review':
                run=self.run_value();run.snapshot_id='changed-snapshot'
                with self.store.connect() as db:db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(asdict(run)),run.run_id))
        self.start();Worker(self.service,fault=change).once()
        self.assertEqual(self.job()['status'],'blocked');self.assertIsNone(self.run_value().review)
        self.assertEqual(self.model.calls.count('review'),1)
    def test_unsettled_usage_blocks_recovery(self):
        self.install_review(lambda raw:{})
        def unknown(point,stage):
            if point=='after_response' and stage=='review':
                with self.store.connect() as db:db.execute("UPDATE live_calls SET actual=NULL WHERE run_id=? AND stage='review'",(self.run_id,))
        self.start();Worker(self.service,fault=unknown).once()
        self.assertEqual(self.job()['status'],'blocked');self.assertIsNone(self.run_value().review)
        self.assertEqual(self.model.calls.count('review'),1)
    def test_provider_failure_does_not_handoff(self):
        base=self.model.complete
        def fail(messages):
            raw,tokens=base(messages)
            if self.model.calls[-1]=='review':raise DomainError('MODEL_OUTPUT_INVALID','provider cannot settle response')
            return raw,tokens
        self.model.complete=fail
        self.start();Worker(self.service).once()
        self.assertEqual(self.job()['status'],'blocked');self.assertIsNone(self.run_value().review)
        self.assertEqual(self.audit()[2:4],('failed','failed'))
    def test_inflight_state_with_token_field_cannot_handoff(self):
        self.install_review(lambda raw:{})
        def inflight(point,stage):
            if point=='after_response' and stage=='review':
                with self.store.connect() as db:db.execute("UPDATE live_calls SET state='calling' WHERE run_id=? AND stage='review'",(self.run_id,))
        self.start();Worker(self.service,fault=inflight).once()
        self.assertEqual(self.job()['status'],'blocked')
        self.assertIsNone(self.run_value().review)
        self.assertEqual(self.audit()[2],'calling')
    def test_valid_review_is_validated_after_domain_transition(self):
        self.start();Worker(self.service).once()
        self.assertEqual(self.job()['status'],'waiting')
        self.assertEqual(self.audit()[2:4],('validated','validated'));self.assertIsNone(self.audit()[4])

    def test_cancelled_run_cannot_receive_handoff(self):
        self.install_review(lambda raw:{})
        def cancel(point,stage):
            if point=='after_response' and stage=='review':
                self.service.action(self.owner,self.run_id,dict(action='cancel',version=self.run_value().status_version,key=str(uuid4()),payload={}))
        self.start();Worker(self.service,fault=cancel).once()
        self.assertEqual(self.run_value().run_status,'CANCELLED')
        self.assertIsNone(self.run_value().review)
        self.assertEqual(self.job()['status'],'done')

    def test_handoff_manual_confirmation_exports_exact_draft(self):
        self.install_review(lambda raw:{})
        self.start();Worker(self.service).once()
        run=self.assert_handoff({});draft=run.drafts[-1]
        self.service.action(self.owner,self.run_id,dict(action='adopt_manual',version=run.status_version,key=str(uuid4()),payload=dict(draft_ref=draft['ref'],content_hash=draft['content_hash'],acknowledge=True)))
        run=self.run_value()
        self.assertEqual(run.run_status,'SUCCEEDED')
        self.assertEqual(run.acceptance['mode'],'manual_override')
        exported=self.service.export(self.owner,self.run_id)
        self.assertIn(draft['content']['body'],exported)
        self.assertNotIn('未通过 AI 审核',exported)
        self.assertNotIn('用户人工采用',exported)
        self.assertEqual(self.model.calls.count('review'),1)

    def sync_until_review(self):
        for _ in range(7):
            run=self.run_value()
            result=self.service.executor.step(self.run_id,self.owner,run.status_version,str(uuid4()))
        return result

    def test_sync_invalid_review_handoff_and_command_idempotency(self):
        self.install_review(lambda raw:{})
        for _ in range(6):
            run=self.run_value();self.service.executor.step(self.run_id,self.owner,run.status_version,str(uuid4()))
        run=self.run_value();key=str(uuid4());version=run.status_version
        first=self.service.executor.step(self.run_id,self.owner,version,key)
        second=self.service.executor.step(self.run_id,self.owner,version,key)
        self.assertEqual(first,second)
        self.assertEqual(first.run_status,'WAITING_USER')
        self.assertEqual(first.review['decision'],'needs_human')
        self.assertEqual(self.audit()[1:4],(120,'invalid','invalid'))
        self.assertEqual(len(first.reviews),1)
        self.assertEqual(self.model.calls.count('review'),1)

    def test_sync_second_layer_invalid_review_handoff(self):
        original=Run.reviewed
        def reject_once(run,report,gates,fail_on_limit=False):
            if not report.get('recovery_kind'):raise DomainError('MODEL_OUTPUT_INVALID','sync second layer schema failure')
            return original(run,report,gates,fail_on_limit=fail_on_limit)
        with patch.object(Run,'reviewed',reject_once):run=self.sync_until_review()
        self.assertEqual(run.run_status,'WAITING_USER')
        self.assertEqual(run.review['decision'],'needs_human')
        self.assertEqual(self.audit()[2:4],('invalid','invalid'))

    def test_sync_cancellation_discards_received_review(self):
        def cancel(raw):
            self.service.action(self.owner,self.run_id,dict(action='cancel',version=self.run_value().status_version,key=str(uuid4()),payload={}))
            return {}
        self.install_review(cancel)
        run=self.sync_until_review()
        self.assertEqual(run.run_status,'CANCELLED')
        self.assertIsNone(run.review)
        self.assertEqual(self.audit()[1],120)

    def test_sync_valid_review_preserves_normal_approval(self):
        run=self.sync_until_review()
        self.assertEqual(run.review['decision'],'approved')
        self.assertEqual(self.audit()[2:4],('validated','validated'))

    def test_three_genuine_rejections_stop_at_human_and_export_with_acknowledgement(self):
        run=self.run_value();run.context.pop('material_policy',None)
        with self.store.connect() as db:db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(asdict(run)),run.run_id))
        def reject(raw):
            raw.update(decision='revision_required',next_action='revise',issues=[dict(issue_id='same',severity='major',state='open',location='body',excerpt='正文',reason='仍不满足需求',suggestion='增加具体内容')])
            raw['previous_issue_results']=[dict(issue_id='same',result='unresolved')] if self.model.calls.count('review')>1 else []
            return raw
        self.install_review(reject)
        self.start();Worker(self.service).once()
        run=self.run_value()
        self.assertEqual(run.run_status,'WAITING_USER')
        self.assertEqual(run.wait_reason,'revision_limit')
        self.assertEqual(self.job()['status'],'waiting')
        self.assertEqual(run.review['decision'],'revision_required')
        self.assertEqual(len(run.drafts),3)
        self.assertEqual(len(run.reviews),3)
        self.assertLessEqual(self.model.calls.count('review'),3)
        self.assertEqual(self.model.calls.count('body')+self.model.calls.count('revise'),3)
        self.assertLessEqual(len(self.model.calls),12)
        calls=len(self.model.calls)
        actions=self.service.view(run)['allowed_actions']
        self.assertIn('adopt_manual',actions)
        self.assertNotIn('next',actions)
        self.assertNotIn('request_revision',actions)
        self.assertNotIn('accept',actions)
        with self.assertRaises(DomainError):self.start()
        draft=run.drafts[-1]
        self.service.action(self.owner,self.run_id,dict(action='adopt_manual',version=run.status_version,key=str(uuid4()),payload=dict(draft_ref=draft['ref'],content_hash=draft['content_hash'],acknowledge=True)))
        self.assertIn(draft['content']['body'],self.service.export(self.owner,self.run_id))
        self.assertEqual(len(self.model.calls),calls)

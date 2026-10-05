"""Provider substitutions must obey the same domain guards and cost ledger."""
import json
import unittest
from uuid import uuid4
import test_live_provider as fixtures
from backend.model_router import ModelRouter, Route
from backend.execution import Executor
from backend.contracts import DomainError


class RouterTests(unittest.TestCase):
    setUp=fixtures.LiveTests.setUp
    tearDown=fixtures.LiveTests.tearDown
    step=fixtures.LiveTests.step
    until_review=fixtures.LiveTests.until_review
    def test_different_models_share_rules_and_record_provenance(self):
        alternate=fixtures.FixtureModel()
        router=ModelRouter(self.config,self.model,{'research':Route('offline','test-research')},{('offline','test-research'):alternate})
        self.executor=Executor(self.store,self.config,router)
        run=self.until_review()
        self.assertEqual(alternate.calls,['research'])
        with self.store.connect() as db:
            rows=db.execute('SELECT provider,model,sources,input_hash,snapshot_id,outcome FROM model_audit').fetchall()
        self.assertEqual(len(rows),8)
        self.assertTrue(all(r[2] and r[3] and r[4]=='snapshot' and r[5]=='validated' for r in rows))
        self.assertIn(('offline','test-research'),[(r[0],r[1]) for r in rows])
        with self.assertRaises(DomainError):
            self.store.command(run.run_id,'me',run.status_version,'bad-approve','accept',{'draft_ref':'wrong','review_ref':run.review['ref']})
        calls=self.executor.public(run)['calls']
        self.assertTrue(all(c['sources'][0]['source_type']=='user_provided' for c in calls))
        self.assertTrue(all(c['duration_ms'] is not None for c in calls))
        self.assertTrue(all(c['input_tokens'] is None for c in calls))

    def test_expensive_route_is_reserved_before_network(self):
        router=ModelRouter(self.config,self.model,{'audience':Route('fixture','expensive',0.001),'research':Route('fixture','expensive',0.001)})
        self.executor=Executor(self.store,self.config,router)
        self.step()
        self.assertEqual(self.model.calls,[])
        self.assertEqual(self.run.run_status,'FAILED')

    def test_failed_calls_have_audit_and_unknown_usage(self):
        def fail(messages):raise TimeoutError('potential secret')
        self.model.complete=fail;self.step()
        with self.store.connect() as db:
            count=db.execute('SELECT COUNT(*) FROM model_audit').fetchone()[0]
            calls=db.execute('SELECT COUNT(*) FROM live_calls').fetchone()[0]
        self.assertEqual(count,calls);self.assertGreater(count,0)
        view=self.executor.public(self.run)
        self.assertEqual(view['usage']['unknown_calls'],calls)
        self.assertNotIn('potential secret',json.dumps(view))

    def test_alternate_reviewer_cannot_bypass_review_gates(self):
        alternate=fixtures.FixtureModel();base=alternate.complete
        def unsafe(messages):
            value,tokens=base(messages)
            value['checks'][0]['result']='fail'
            return value,tokens
        alternate.complete=unsafe
        router=ModelRouter(self.config,self.model,{'review':Route('offline','different-reviewer')},{('offline','different-reviewer'):alternate})
        self.executor=Executor(self.store,self.config,router)
        for _ in range(7):self.step()
        self.assertEqual(self.run.run_status,'FAILED')
        with self.assertRaises(DomainError):
            self.store.command(self.run.run_id,'me',self.run.status_version,'unsafe','accept',{'draft_ref':self.run.drafts[-1]['ref'],'review_ref':'forged'})

    def test_known_parse_retries_keep_original_stage_limit(self):
        from backend.provider import ProviderOutputError
        attempts=[]
        def invalid(messages):
            attempts.append(1)
            raise ProviderOutputError('模型返回空内容',tokens=120,metadata={})
        self.model.complete_result=invalid
        messages=[{'role':'user','content':'json'}]
        for _ in range(3):
            with self.assertRaises(DomainError) as caught:
                self.executor.calls.invoke(self.run,'audience','audience',messages,lambda db:None,reuse=True)
            self.assertEqual(caught.exception.code,'MODEL_OUTPUT_INVALID')
        with self.assertRaises(DomainError) as caught:
            self.executor.calls.invoke(self.run,'audience','audience',messages,lambda db:None,reuse=True)
        self.assertEqual(caught.exception.code,'STAGE_ATTEMPT_LIMIT')
        self.assertEqual(len(attempts),3)
        self.assertEqual(self.executor.public(self.run)['usage']['tokens'],360)
        self.assertEqual(self.executor.public(self.run)['usage']['unknown_calls'],0)

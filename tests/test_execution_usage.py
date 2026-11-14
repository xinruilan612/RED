"""Public usage separates never-sent transport attempts from model calls."""
import unittest
import test_live_provider as fixtures
from backend.provider import RATE


class ExecutionUsageTests(unittest.TestCase):
    setUp = fixtures.LiveTests.setUp
    tearDown = fixtures.LiveTests.tearDown

    def insert_call(self, call_id, state, actual, reserved=1000):
        with self.store.connect() as db:
            db.execute('INSERT INTO live_calls(id,run_id,agent,stage,reserved,actual,state,error) VALUES(?,?,?,?,?,?,?,?)',
                       (call_id,self.run.run_id,'audience','audience',reserved,actual,state,'连接记录'))

    def test_never_sent_attempts_remain_auditable_without_usage_or_budget(self):
        self.insert_call('dns-failure','not_sent',0)
        result=self.executor.public(self.run)
        self.assertEqual(len(result['calls']),1)
        self.assertEqual(result['calls'][0]['status'],'not_sent')
        self.assertEqual(result['calls'][0]['error'],'连接记录')
        self.assertEqual(result['calls'][0]['reserved_tokens'],1000)
        self.assertEqual(result['usage']['model_calls'],0)
        self.assertEqual(result['usage']['tokens'],0)
        self.assertEqual(result['usage']['unknown_calls'],0)
        self.assertEqual(result['usage']['cost_upper_estimate_usd'],0)

    def test_received_usage_and_ambiguous_failures_keep_their_original_accounting(self):
        self.insert_call('dns-failure','not_sent',0)
        self.insert_call('response','validated',120)
        self.insert_call('timeout','failed',None,2000)
        result=self.executor.public(self.run)
        self.assertEqual(len(result['calls']),3)
        self.assertEqual(result['usage']['model_calls'],2)
        self.assertEqual(result['usage']['tokens'],120)
        self.assertEqual(result['usage']['unknown_calls'],1)
        self.assertEqual(result['usage']['cost_upper_estimate_usd'],round((120+2000)*RATE,6))

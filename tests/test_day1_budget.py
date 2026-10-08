"""Hard experiment cap: adapter fixtures only, never network calls."""
import os
import threading
import unittest
from uuid import uuid4
from tests import test_testing_budget as budget_tests
from backend.contracts import DomainError
from backend.model_router import Calls, ModelRouter, Route
from backend.provider import Config
from backend.testing_budget import initialize, public
from backend.store import Store
from backend.execution import Executor


class Day1BudgetTests(unittest.TestCase):
    setUp = budget_tests.TestingBudgetTests.setUp
    tearDown = budget_tests.TestingBudgetTests.tearDown
    hold = budget_tests.TestingBudgetTests.hold

    def test_cap_blocks_before_provider_and_keeps_advisory_default(self):
        class Adapter:
            count=0
            def complete_result(inner,messages):
                inner.count+=1
                return {},10,{'input_tokens':8,'output_tokens':2}
        adapter=Adapter();config=Config('fixture')
        router=ModelRouter(config,routes={'research':Route('deepseek','deepseek-flash')},adapters={('deepseek','deepseek-flash'):adapter})
        self.run.context['model_policy']=router.policy()
        initialize(self.store,'owner',.00001,hard_limit=True)
        with self.assertRaises(DomainError) as error:
            Calls(self.store,config,router).invoke(self.run,'research','research',[{'content':'test'}],lambda db:None)
        self.assertEqual(error.exception.code,'TEST_BUDGET_EXCEEDED')
        self.assertEqual(adapter.count,0)
        self.assertEqual(public(self.store,'owner')['spent_cny'],0)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM testing_budget_reservations').fetchone()[0],0)
        self.assertFalse(initialize(self.store,'unrelated',.00001)['hard_limit'])

    def test_concurrent_reservations_cannot_both_spend_remaining_cap(self):
        initialize(self.store,'owner',.04,hard_limit=True)
        barrier=threading.Barrier(2);results=[]
        def invoke():
            barrier.wait()
            try:self.hold();results.append('reserved')
            except DomainError as exc:results.append(exc.code)
        threads=[threading.Thread(target=invoke) for _ in range(2)]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertCountEqual(results,['reserved','TEST_BUDGET_EXCEEDED'])
        self.assertEqual(public(self.store,'owner')['spent_cny'],.02608)

    def test_unknown_failure_keeps_full_hold_and_blocks_other_lineage(self):
        initialize(self.store,'owner',5,hard_limit=True)
        cid=self.hold()
        before=public(self.store,'owner')['spent_cny']
        with self.store.connect() as db:
            db.execute("UPDATE live_calls SET state='failed' WHERE id=?",(cid,))
        self.assertEqual(public(self.store,'owner')['spent_cny'],before)
        self.run.workflow_type='operations';self.run.context['paid_scope_confirmed']=True
        self.run.run_id=str(uuid4())
        with self.assertRaises(DomainError) as error:self.hold()
        self.assertEqual(error.exception.code,'USAGE_UNKNOWN')
        self.assertEqual(public(self.store,'owner')['spent_cny'],before)

    def test_baseline_and_recovery_share_owner_cap(self):
        initialize(self.store,'owner',.06,hard_limit=True)
        original=self.run.run_id
        self.hold()
        self.run.run_id=str(uuid4())  # Resume shares root.
        self.hold(root=original)
        self.run.run_id=str(uuid4())  # Single-call baseline has operations type.
        self.run.workflow_type='operations';self.run.context['paid_scope_confirmed']=True
        with self.assertRaises(DomainError) as error:self.hold()
        self.assertEqual(error.exception.code,'TEST_BUDGET_EXCEEDED')
        status=public(self.store,'owner')
        self.assertEqual(status['spent_cny'],.05216)
        self.assertEqual(status['run_count'],1)

    def test_completed_and_invalid_calls_settle_without_losing_charges(self):
        initialize(self.store,'owner',.03,hard_limit=True)
        cid=self.hold()
        with self.store.connect() as db:
            db.execute("UPDATE live_calls SET state='invalid',actual=100 WHERE id=?",(cid,))
            db.execute('UPDATE model_audit SET input_tokens=80,output_tokens=20 WHERE call_id=?',(cid,))
        self.assertEqual(public(self.store,'owner')['spent_cny'],.00032)
        self.hold()
        self.assertEqual(public(self.store,'owner')['spent_cny'],.02640)

    def test_opt_in_persists_and_cannot_silently_disable_or_reset(self):
        initialize(self.store,'owner',5)
        self.hold()
        initialize(self.store,'owner',5,hard_limit=True)
        before=public(self.store,'owner')
        self.assertEqual(before['spent_cny'],.02608)
        self.assertTrue(initialize(self.store,'owner',5)['hard_limit'])
        self.assertEqual(public(Store(self.store.path),'owner'),before)
        with self.assertRaises(DomainError):initialize(self.store,'owner',6,hard_limit=True)
        self.assertEqual(public(self.store,'owner'),before)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires actual PostgreSQL')
class PostgresDay1BudgetTests(Day1BudgetTests):
    def setUp(self):
        import psycopg
        self.schema='youji_day1_budget_'+uuid4().hex
        self.base=os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('CREATE SCHEMA '+self.schema)
        self.store=Store(self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema)
        Executor(self.store,Config('fixture'))
        self.run=self.store.create('owner','snapshot',{'mode':'live'})
    def tearDown(self):
        import psycopg
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('DROP SCHEMA '+self.schema+' CASCADE')

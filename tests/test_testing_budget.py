"""Persistent experiment guidance is shared across resumes, with no provider calls."""
import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from backend.store import Store
from backend.execution import Executor
from backend.provider import Config
from backend.model_router import Route
from backend.contracts import DomainError
from backend.testing_budget import initialize, public, reserve, _cost


class TestingBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'budget.sqlite')
        Executor(self.store,Config('fixture'))
        self.run=self.store.create('owner','snapshot',{'mode':'live'})
    def tearDown(self):self.tmp.cleanup()
    def hold(self,run=None,root=None):
        run=run or self.run;root=root or run.run_id;cid=str(uuid4())
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO live_lineage VALUES(?,?) ON CONFLICT(run_id) DO NOTHING',(run.run_id,root))
            reserve(db,run,root,Route('deepseek','deepseek-flash'),[{'content':'test'}],cid)
            db.execute('INSERT INTO live_calls(id,run_id,agent,stage,reserved,state) VALUES(?,?,?,?,?,?)',(cid,run.run_id,'research','research',3260,'calling'))
            db.execute('INSERT INTO model_audit(call_id,run_id,agent,stage,provider,model,route_version,prompt_version,input_hash,sources,snapshot_id,started,rate,outcome) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(cid,run.run_id,'research','research','deepseek','deepseek-flash','v','v','hash','[]','s',0,.000008,'calling'))
        return cid
    def test_historical_split_cost_and_idempotent_initialization(self):
        cid=self.hold()
        with self.store.connect() as db:
            db.execute("UPDATE live_calls SET actual=29065,reserved=40000,state='invalid' WHERE id=?",(cid,))
            db.execute('UPDATE model_audit SET input_tokens=25223,output_tokens=3842 WHERE call_id=?',(cid,))
        result=initialize(self.store,'owner',.30,existing_run_ids=[self.run.run_id])
        self.assertEqual(result['spent_cny'],.081182)
        self.assertEqual(result['run_count'],1)
        self.assertEqual(initialize(self.store,'owner',.30,existing_run_ids=[self.run.run_id]),result)
        with self.assertRaises(DomainError):initialize(self.store,'owner',1)
        self.assertEqual(public(self.store,'owner'),result)
    def test_pending_reservation_warns_above_target_and_is_persistent(self):
        initialize(self.store,'owner',.03)
        cid=self.hold()
        self.assertEqual(public(self.store,'owner')['spent_cny'],.024520)
        self.assertIn('已接近',public(self.store,'owner')['warning'])
        self.hold()
        status=public(self.store,'owner')
        self.assertTrue(status['over_target'])
        self.assertIn('仍可继续',status['warning'])
        self.assertEqual(status['target_cny'],.03)
        with self.store.connect() as db:
            db.execute("UPDATE live_calls SET state='failed' WHERE id=?",(cid,))
        self.assertEqual(public(Store(self.store.path),'owner')['spent_cny'],.05060)
    def test_three_roots_are_reference_and_fourth_is_allowed(self):
        initialize(self.store,'owner',1,max_runs=3)
        self.hold()
        # Use cancelled snapshots to allow creating independent runs.
        import json
        with self.store.connect() as db:
            payload=json.loads(db.execute('SELECT payload FROM runs WHERE id=?',(self.run.run_id,)).fetchone()[0])
            payload['run_status']='CANCELLED'
            db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(payload),self.run.run_id))
        for index in range(2):
            run=self.store.create('owner','s',{'mode':'live'})
            self.hold(run)
            with self.store.connect() as db:
                payload=json.loads(db.execute('SELECT payload FROM runs WHERE id=?',(run.run_id,)).fetchone()[0]);payload['run_status']='CANCELLED'
                db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(payload),run.run_id))
        self.hold(self.run)
        self.assertEqual(public(self.store,'owner')['run_count'],3)
        fourth=self.store.create('owner','s',{'mode':'live'})
        self.hold(fourth)
        status=public(self.store,'owner')
        self.assertEqual(status['run_count'],4)
        self.assertEqual(status['target_runs'],3)
        self.assertTrue(status['over_target'])
        self.assertTrue(status['warning'])
        initialize(self.store,'owner',1,max_runs=3,existing_run_ids=[fourth.run_id])
        self.assertIsNone(public(self.store,'another-owner'))
    def test_unknown_models_and_owner_mismatch_are_rejected(self):
        initialize(self.store,'owner',.30)
        with self.store.connect() as db:
            with self.assertRaises(DomainError):reserve(db,self.run,self.run.run_id,Route('other','model'),[{'content':'x'}],'call')
        with self.assertRaises(DomainError):initialize(self.store,'other',.30,existing_run_ids=[self.run.run_id])
        self.assertIsNone(public(self.store,'other'))
    def test_bad_or_missing_split_usage_never_gets_input_discount(self):
        base=[100,200,None,None,'deepseek','deepseek-flash','received',None]
        self.assertEqual(_cost(base),800)
        base[2:4]=[99,2]
        self.assertEqual(_cost(base),800)
        base[0]=None;base[6]='failed'
        self.assertEqual(_cost(base),1600)

    def test_calls_integration_settles_and_continues_above_target(self):
        from backend.model_router import Calls, ModelRouter
        class Adapter:
            count=0
            def complete_result(inner,messages):
                inner.count+=1
                return {},10,{'input_tokens':8,'output_tokens':2}
        adapter=Adapter()
        config=Config('fixture')
        router=ModelRouter(config,routes={'research':Route('deepseek','deepseek-flash')},adapters={('deepseek','deepseek-flash'):adapter})
        self.run.context['model_policy']=router.policy()
        initialize(self.store,'owner',.00001)
        calls=Calls(self.store,config,router)
        calls.invoke(self.run,'research','research',[{'content':'test'}],lambda db:None)
        self.assertEqual(public(self.store,'owner')['spent_cny'],.000032)
        self.assertTrue(public(self.store,'owner')['over_target'])
        calls.invoke(self.run,'research','research',[{'content':'test'}],lambda db:None)
        self.assertEqual(adapter.count,2)
        self.assertEqual(public(self.store,'owner')['spent_cny'],.000064)

    def test_paid_auxiliary_scopes_require_exact_boolean_confirmation(self):
        initialize(self.store,'owner',.30)
        self.hold()  # Preserve a pre-existing creation charge.
        baseline=public(self.store,'owner')
        for workflow in ('operations','windtunnel'):
            self.run.workflow_type=workflow
            for flag in (None,False,1,'true',{},[]):
                with self.subTest(workflow=workflow,flag=flag):
                    if flag is None:self.run.context.pop('paid_scope_confirmed',None)
                    else:self.run.context['paid_scope_confirmed']=flag
                    with self.assertRaises(DomainError) as error:self.hold()
                    self.assertEqual(error.exception.code,'TEST_BUDGET_SCOPE')
                    self.assertEqual(public(self.store,'owner'),baseline)
                    with self.store.connect() as db:
                        self.assertEqual(db.execute('SELECT COUNT(*) FROM testing_budget_reservations').fetchone()[0],1)
        # Even a confirmation does not broaden authorization to unknown workflows.
        self.run.workflow_type='unknown'
        self.run.context['paid_scope_confirmed']=True
        with self.assertRaises(DomainError) as error:self.hold()
        self.assertEqual(error.exception.code,'TEST_BUDGET_SCOPE')
        self.assertEqual(public(self.store,'owner'),baseline)

    def test_confirmed_scopes_reuse_persistent_budget_without_clearing_creation_usage(self):
        initialize(self.store,'owner',.30)
        self.hold()
        first=public(self.store,'owner')
        for workflow in ('operations','windtunnel'):
            self.run.workflow_type=workflow
            self.run.context['paid_scope_confirmed']=True
            self.hold()
        combined=public(self.store,'owner')
        self.assertEqual(combined['spent_cny'],round(first['spent_cny']*3,6))
        self.assertEqual(combined['run_count'],1)  # The same lineage retains one root.
        self.assertEqual(combined['target_cny'],.30)
        self.assertEqual(public(Store(self.store.path),'owner'),combined)
        self.assertEqual(initialize(self.store,'owner',.30),combined)
        with self.assertRaises(DomainError):initialize(self.store,'owner',1)
        self.assertEqual(public(self.store,'owner'),combined)

    def test_creation_scope_keeps_original_behavior_without_paid_confirmation(self):
        initialize(self.store,'owner',.30)
        self.assertEqual(self.run.workflow_type,'creation')
        self.hold()
        self.run.context['paid_scope_confirmed']=False
        self.hold()
        status=public(self.store,'owner')
        self.assertEqual(status['run_count'],1)
        self.assertEqual(status['spent_cny'],.04904)

    def test_concurrent_reservations_are_both_accounted_without_target_block(self):
        import threading
        initialize(self.store,'owner',.03)
        barrier=threading.Barrier(2);results=[]
        def invoke():
            barrier.wait()
            try:self.hold();results.append('reserved')
            except DomainError as exc:results.append(exc.code)
        threads=[threading.Thread(target=invoke) for _ in range(2)]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(results,['reserved','reserved'])
        self.assertEqual(public(self.store,'owner')['spent_cny'],.04904)
        self.assertTrue(public(self.store,'owner')['over_target'])


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires actual PostgreSQL')
class PostgresTestingBudgetTests(TestingBudgetTests):
    def setUp(self):
        import psycopg
        self.schema='youji_budget_test_'+uuid4().hex
        self.base=os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base,autocommit=True) as db:
            db.execute('CREATE SCHEMA '+self.schema)
        target=self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema
        self.store=Store(target)
        Executor(self.store,Config('fixture'))
        self.run=self.store.create('owner','snapshot',{'mode':'live'})

    def tearDown(self):
        import psycopg
        with psycopg.connect(self.base,autocommit=True) as db:
            db.execute('DROP SCHEMA '+self.schema+' CASCADE')

"""Offline ledger tests; adapters never send model requests."""
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
from backend.contracts import DomainError
from backend.creation_algorithms import options

spec=importlib.util.spec_from_file_location('sprint_live_experiment',Path(__file__).resolve().parents[1]/'scripts'/'sprint_live_experiment.py')
e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)

class Adapter:
    def __init__(self,result=None,error=None):self.result=result or ({'fixture':True},100,{'request_id':'offline-fixture'});self.error=error;self.calls=0
    def complete_result(self,*args,**kwargs):
        self.calls+=1
        if self.error:raise self.error
        return self.result

class CumulativeCapTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'budget.sqlite'
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE attempts(id TEXT PRIMARY KEY,reserved INTEGER,billed INTEGER,tokens INTEGER,state TEXT)')
        self.adapter=Adapter()
    def insert(self,identity='old',reserved=10000,billed=800,tokens=100,state='received'):
        with sqlite3.connect(self.path) as db:db.execute('INSERT INTO attempts VALUES(?,?,?,?,?)',(identity,reserved,billed,tokens,state))
    def rows(self):
        with sqlite3.connect(self.path) as db:return db.execute('SELECT reserved,billed,tokens,state FROM attempts ORDER BY rowid').fetchall()
    def test_old_spending_retained_and_success_settles_only_own_reservation(self):
        self.insert(billed=4000000,tokens=500000,reserved=4000000)
        cap=e.CumulativeCap(self.adapter,self.path)
        self.assertEqual(cap.spent(),4000000)
        value,tokens,meta=cap.complete_result([{'role':'user','content':'fixture'}],max_tokens=100)
        self.assertEqual(tokens,100);self.assertEqual(cap.spent(),4000800)
        self.assertEqual(self.rows()[0][1],4000000)
        self.assertEqual(self.rows()[1][1:],(800,100,'received'))
    def test_missing_or_disappeared_ledger_never_recreated(self):
        cap=e.CumulativeCap(self.adapter,self.path);self.path.unlink()
        with self.assertRaises(sqlite3.OperationalError):cap.complete_result([])
        self.assertFalse(self.path.exists());self.assertEqual(self.adapter.calls,0)
        with self.assertRaises(ValueError):e.CumulativeCap(self.adapter,self.path)
        self.assertFalse(self.path.exists())
    def test_unknown_and_inflight_history_block_before_send(self):
        for state in ('unknown','calling'):
            with self.subTest(state=state):
                with sqlite3.connect(self.path) as db:db.execute('DELETE FROM attempts')
                self.insert(state=state,billed=None,tokens=None)
                cap=e.CumulativeCap(self.adapter,self.path)
                with self.assertRaises(DomainError):cap.complete_result([])
                self.assertEqual(len(self.rows()),1)
        self.assertEqual(self.adapter.calls,0)
    def test_budget_cap_refuses_without_sending_or_creating_attempt(self):
        self.insert(reserved=9999999,billed=9999999,tokens=1)
        cap=e.CumulativeCap(self.adapter,self.path)
        with self.assertRaises(DomainError):cap.complete_result([])
        self.assertEqual(self.adapter.calls,0);self.assertEqual(len(self.rows()),1)
    def test_unsent_failure_releases_own_hold_and_other_failure_stays_unknown(self):
        for code,state in [('MODEL_REQUEST_NOT_SENT','not_sent'),('MODEL_OUTPUT_INVALID','unknown')]:
            with self.subTest(code=code):
                with sqlite3.connect(self.path) as db:db.execute('DELETE FROM attempts')
                adapter=Adapter(error=DomainError(code,'offline fixture'))
                cap=e.CumulativeCap(adapter,self.path)
                with self.assertRaises(DomainError):cap.complete_result([])
                self.assertEqual(self.rows()[0][-1],state)
                if state=='not_sent':self.assertEqual(cap.spent(),0)
                else:
                    self.assertGreater(cap.spent(),0)
                    with self.assertRaises(DomainError):cap.complete_result([])
                    self.assertEqual(adapter.calls,1)
    def test_invalid_or_excess_usage_remains_unknown_and_blocks_future_send(self):
        for tokens in (None,True,-1,1000000):
            with self.subTest(tokens=tokens):
                with sqlite3.connect(self.path) as db:db.execute('DELETE FROM attempts')
                adapter=Adapter(result=({},tokens,{}));cap=e.CumulativeCap(adapter,self.path)
                with self.assertRaises(DomainError):cap.complete_result([],max_tokens=100)
                self.assertEqual(self.rows()[0][-1],'unknown')
                with self.assertRaises(DomainError):cap.complete_result([])
                self.assertEqual(adapter.calls,1)
    def test_bad_ledger_or_request_limits_fail_closed(self):
        for cap in (0,-1,10.01,float('nan')):
            with self.assertRaises(ValueError):e.CumulativeCap(self.adapter,self.path,cap)
        cap=e.CumulativeCap(self.adapter,self.path)
        for limit in (True,0,6001):
            with self.assertRaises(DomainError):cap.complete_result([],max_tokens=limit)
        with self.assertRaises(DomainError):cap.complete_result([{'content':'x'*100001}])
        self.assertEqual(self.adapter.calls,0)
        self.insert(reserved=-1)
        with self.assertRaises(ValueError):e.CumulativeCap(self.adapter,self.path)
    def test_dataset_projection_keeps_sealed_answer_out_of_initial_input(self):
        task={'id':'D01','answer':'sealed-secret','input':{'topic':'虚构任务','audience':'虚构读者','material':'原始事实',
              'creation':{'domains':['digital'],'word_count':300},'answer':'also-sealed'},'gold':'not-model-input'}
        tasks,answers=e.study_inputs({'items':[task]},{'items':[{'task_id':'D01','fixed_answer':'统一补料'}]})
        self.assertEqual(answers,{'D01':'统一补料'})
        self.assertEqual(set(e.creation_input(tasks[0])),{'topic','audience','material','creation'})
        self.assertNotIn('sealed',str(e.creation_input(tasks[0])))

    def test_all_production_stage_output_limits_are_allowed_and_settled(self):
        from backend.model_router import STAGE_OUTPUT_TOKENS
        for limit in {3000,*STAGE_OUTPUT_TOKENS.values()}:
            with self.subTest(limit=limit):
                cap=e.CumulativeCap(self.adapter,self.path)
                cap.complete_result([],max_tokens=limit)
                self.assertEqual(self.rows()[-1][-1],'received')
        with self.assertRaises(DomainError) as error:e.CumulativeCap(self.adapter,self.path).complete_result([],max_tokens=6001)
        self.assertEqual(error.exception.code,'MODEL_REQUEST_NOT_SENT')

    def test_transport_lock_serializes_parallel_fixtures_and_does_not_fake_unknown(self):
        from concurrent.futures import ThreadPoolExecutor
        import time
        class SlowAdapter(Adapter):
            def complete_result(inner,*args,**kwargs):
                time.sleep(.02)
                return super(SlowAdapter,inner).complete_result(*args,**kwargs)
        adapters=[SlowAdapter(),SlowAdapter()]
        caps=[e.CumulativeCap(adapter,self.path) for adapter in adapters]
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(lambda cap:cap.complete_result([],max_tokens=6000),caps))
        self.assertEqual(len(results),2)
        self.assertEqual([row[-1] for row in self.rows()],['received','received'])
        self.assertEqual([adapter.calls for adapter in adapters],[1,1])
        self.insert(identity='truly-unknown',billed=None,tokens=None,state='unknown')
        with self.assertRaises(DomainError) as error:caps[0].complete_result([])
        self.assertEqual(error.exception.code,'MODEL_REQUEST_NOT_SENT')
        self.assertEqual(adapters[0].calls,1)

    def test_public_summary_records_early_stop_without_credentials(self):
        report=e.public_summary({'password':'private','account_id':'private','references':{},'cases':[],
                                 'source_model':'fixture','extra_secret':'private'},12345,'budget_stop_before_new_case')
        self.assertEqual(report['stop_reason'],'budget_stop_before_new_case')
        self.assertEqual(report['cumulative_upper_micro'],12345)
        self.assertNotIn('private',str(report))
        self.assertIn('不能估计',report['scope'])

    def test_ten_yuan_authorization_includes_old_4800336_micro_spending(self):
        self.insert(reserved=4800336,billed=4800336,tokens=600042)
        cap=e.CumulativeCap(self.adapter,self.path,10)
        self.assertEqual(cap.limit,10000000)
        cap.complete_result([],max_tokens=6000)
        self.assertEqual(cap.spent(),4801136)
        self.assertEqual(self.rows()[0][1],4800336)
        self.insert(identity='later-spend',reserved=5198863,billed=5198863,tokens=1)
        with self.assertRaises(DomainError) as error:cap.complete_result([])
        self.assertEqual(error.exception.code,'MODEL_REQUEST_NOT_SENT')
        self.assertEqual(self.adapter.calls,1)

    def test_new_case_threshold_follows_authorization_instead_of_old_48_yuan_stop(self):
        self.assertFalse(e.stop_before_new_case(4800336,10))
        self.assertFalse(e.stop_before_new_case(9799999,10))
        self.assertTrue(e.stop_before_new_case(9800000,10))
        self.assertTrue(e.stop_before_new_case(4800000,5))
        with self.assertRaises(ValueError):e.stop_before_new_case(0,11)

    def test_public_source_ae_metadata_records_same_initial_hash_and_not_user_submission(self):
        task={'id':'PUB01','input':{'topic':'公开资料构造任务','audience':'普通读者','material':'官方摘录',
              'creation':{'word_count':300}},'answer':'sealed','sources':[{'url':'https://example.org/official'}]}
        design=e.experiment_metadata({'items':[task]},[task],['PUB01'],['A','E'],'dataset-hash','answer-hash',10,'public-source-constructed')
        self.assertEqual(design['groups'],['A','E'])
        self.assertFalse(design['is_user_submission'])
        self.assertFalse(design['has_human_quality_scores'])
        self.assertEqual(len(design['provenance']['initial_input_sha256']['PUB01']),64)
        self.assertNotIn('sealed',str(design))
        summary=e.public_summary({'cases':[],'experiment':design},4800336)
        self.assertIn('不是用户投稿',summary['scope'])
        self.assertNotIn('虚构任务',summary['scope'])
        self.assertEqual(summary['experiment']['provenance']['fixed_answers_sha256'],'answer-hash')
        for arms in (['A'],['A','A'],['A','Z']):
            with self.assertRaises(ValueError):e.experiment_metadata({},[task],['PUB01'],arms,'d','a',10)

    def test_five_arms_are_valid_and_isolate_requested_features(self):
        self.assertEqual(set(e.ARMS),set('ABCDE'))
        normalized={key:options(value) for key,value in e.ARMS.items()}
        self.assertFalse(normalized['A']['enabled'])
        self.assertEqual((normalized['B']['coverage'],normalized['B']['structure'],normalized['B']['ask_questions']),(True,False,False))
        self.assertEqual((normalized['C']['coverage'],normalized['C']['structure'],normalized['C']['ask_questions']),(False,False,True))
        self.assertEqual((normalized['D']['coverage'],normalized['D']['structure'],normalized['D']['ask_questions']),(False,True,False))
        self.assertTrue(all(normalized['E'][key] for key in ('coverage','structure','ask_questions')))

if __name__=='__main__':unittest.main()

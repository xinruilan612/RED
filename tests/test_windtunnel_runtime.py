"""Windtunnel integration tests; all live-mode requests use an in-process fixture."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from uuid import uuid4

from backend.contracts import DomainError
from backend.provider import Config
from backend.service import Service
from backend.store import Store
from backend.worker import Worker
from backend import windtunnel as wt


class Fixture:
    def __init__(self, store, owner):
        self.store, self.owner, self.calls = store, owner, []
        self.failure = None

    def complete(self, messages):
        run = next(r for r in self.store.list_runs(self.owner) if r.workflow_type=='windtunnel' and r.run_status=='RUNNING')
        self.calls.append((run.current_stage, messages))
        if self.failure: raise self.failure
        output=wt.simulate(run,run.current_stage)
        if run.current_stage=='wt_patch':
            source=next(s for s in run.windtunnel['sources'] if s['kind']=='material')
            output['patches'][0].update(replacement='\n\n'+source['text'],citations=[{'source_id':source['id'],'quote':source['text']}])
        return output, 100


class WindtunnelRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'wind.sqlite')
        self.prepare()

    def prepare(self):
        self.owner='wind-runtime-owner'
        self.fixture=Fixture(self.store,self.owner)
        self.config=Config('fixture-only-not-a-key',run_budget_usd=10,day_budget_usd=100)
        self.service=Service(self.store,self.config,self.fixture)
        self.account=self.service.operations.read(self.owner)['accounts'][0]['id']
        self.input={'workflow_type':'windtunnel','account_id':self.account,'title':'工具教程',
                    'text':'打开工具。\n\n选择导出。','scene':'工具教程初学者','mode':'live',
                    'materials':[{'title':'测试材料','text':'ONLY_VERIFY_SECRET_SENTINEL：需要版本 3.12。'}]}
        self.run_id=self.service.create(self.owner,self.input)['run_id']

    def tearDown(self):self.tmp.cleanup()
    def value(self):return self.store.get(self.run_id,self.owner)
    def job(self):return self.service.jobs.public(self.run_id,self.owner)
    def action(self,action,payload=None):
        return self.service.action(self.owner,self.run_id,dict(action=action,payload=payload or {},version=self.value().status_version,key=uuid4().hex))
    def start(self):
        return self.service.background(self.owner,self.run_id,dict(action='start',version=self.value().status_version,key=uuid4().hex))
    def work(self, fault=None):
        self.start();Worker(self.service,fault=fault).once()
    def confirm(self):
        cs=wt.conditions(self.value())
        return self.action('confirm_conditions',{'condition_set_id':cs['id'],'condition_hash':cs['hash']})
    def report(self):
        self.work();self.assertEqual(self.value().wait_reason,'wt_confirm_conditions',self.job())
        self.confirm();self.work();self.assertEqual(self.value().wait_reason,'wt_report',self.job())

    def test_complete_patch_recheck_and_export(self):
        self.report();before=wt.draft(self.value());cs=wt.conditions(self.value())
        self.action('propose_patch',{'condition_ids':[cs['conditions'][0]['id']]});self.work()
        patch=self.value().windtunnel['patches'][-1]
        self.action('apply_patch',{'patch_id':patch['id'],'item_ids':[patch['items'][0]['id']],'base_hash':before['hash']})
        self.assertEqual(self.value().windtunnel['drafts'][0],before)
        self.assertTrue(wt.draft(self.value())['text'].startswith(before['text']))
        with self.assertRaises(DomainError):self.service.export(self.owner,self.run_id)
        self.action('recheck',{'condition_set_id':cs['id']});self.work()
        reports=self.value().windtunnel['reports']
        self.assertEqual(len(reports),2);self.assertEqual(reports[0]['condition_hash'],reports[1]['condition_hash'])
        self.assertNotEqual(reports[0]['draft_hash'],reports[1]['draft_hash'])
        self.action('finish');self.assertEqual(self.value().run_status,'SUCCEEDED')
        operations=self.service.operations.read(self.owner)
        with self.assertRaisesRegex(DomainError,'创作工作流'):
            self.service.operations.command(self.owner,dict(action='prepare',version=operations['version'],key=uuid4().hex,payload={'run_id':self.run_id,'draft_ref':None}))
        exported=self.service.export(self.owner,self.run_id)
        self.assertIn('内容预演报告',exported);self.assertIn('不代表',exported)

    def test_cancel_after_edit_does_not_offer_stale_report_export(self):
        self.report()
        before = wt.draft(self.value())
        self.action('edit_draft', {'title': before['title'], 'text': before['text'] + '\n补充说明。', 'base_hash': before['hash']})
        self.action('cancel')
        self.assertNotIn('export', self.service.view(self.value())['allowed_actions'])
        with self.assertRaises(DomainError):
            self.service.export(self.owner, self.run_id)
        self.assertEqual(len(self.value().windtunnel['reports']), 1)

    def test_export_separates_readability_from_fact_support(self):
        self.report()
        exported = self.service.export(self.owner, self.run_id)
        self.assertIn('稿件给出的答案：', exported)
        self.assertIn('有没有讲清楚：', exported)
        self.assertIn('答案有没有依据：', exported)

    def test_reading_and_actual_visible_source_audit_are_isolated(self):
        self.report()
        read=next(n for n in self.value().node_runs if n['stage']=='wt_read')
        self.assertNotIn('ONLY_VERIFY_SECRET_SENTINEL',json.dumps(read,ensure_ascii=False))
        self.assertNotIn('materials',read['input']);self.assertNotIn('reading',read['input'])
        verify=next(n for n in self.value().node_runs if n['stage']=='wt_verify')
        self.assertIn('ONLY_VERIFY_SECRET_SENTINEL',json.dumps(verify['input']))
        with self.store.connect() as db:
            source=db.execute("SELECT sources FROM model_audit WHERE run_id=? AND stage='wt_read'",(self.run_id,)).fetchone()[0]
        self.assertNotIn('ONLY_VERIFY_SECRET_SENTINEL',source)
        self.assertNotIn('material',source)

    def test_response_reuse_and_committed_node_replay(self):
        self.work();self.confirm();tripped=[]
        def crash(point,stage):
            if point=='after_response' and stage=='wt_read' and not tripped:
                tripped.append(1);raise RuntimeError('fixture stop')
        self.work(crash);self.assertEqual(self.job()['status'],'blocked')
        self.work();self.assertEqual(self.value().wait_reason,'wt_report',self.job())
        self.assertEqual(sum(s=='wt_read' for s,_ in self.fixture.calls),1)
        self.action('recheck',{'condition_set_id':wt.conditions(self.value())['id']});tripped.clear()
        def committed(point,stage):
            if point=='after_commit' and stage=='wt_read' and not tripped:
                tripped.append(1);raise RuntimeError('fixture checkpoint stop')
        self.work(committed);self.assertEqual(self.job()['status'],'blocked')
        count=len(self.fixture.calls);self.work()
        self.assertEqual(len(self.fixture.calls),count+1)
        self.assertEqual(len(self.value().windtunnel['reports']),2)

    def test_unknown_transport_blocks_without_retry(self):
        self.work();self.confirm();self.fixture.failure=TimeoutError('private provider secret')
        self.work();self.assertEqual(self.job()['status'],'blocked')
        self.assertNotIn('private provider secret',self.job()['error'])
        before=len(self.fixture.calls);self.fixture.failure=None
        with self.assertRaises(DomainError) as caught:self.start()
        self.assertEqual(caught.exception.code,'USAGE_UNKNOWN')
        self.assertFalse(Worker(self.service).once())
        self.assertEqual(len(self.fixture.calls),before)
        self.assertEqual(self.job()['status'],'blocked')
        self.assertEqual(self.value().windtunnel['reports'],[])

    def test_cancel_wins_late_result(self):
        self.work();self.confirm()
        def cancel(point,stage):
            if point=='after_response' and stage=='wt_read':self.action('cancel')
        self.work(cancel)
        self.assertEqual(self.value().run_status,'CANCELLED');self.assertEqual(self.job()['status'],'done')
        self.assertEqual(self.value().windtunnel['reports'],[])

    def test_pause_then_resume_and_policy_tampering(self):
        self.work();self.confirm();paused=[]
        def pause(point,stage):
            if point=='after_commit' and stage=='wt_read' and not paused:
                paused.append(True)
                self.service.background(self.owner,self.run_id,dict(action='pause',version=self.value().status_version,key=uuid4().hex))
        self.work(pause);self.assertEqual(self.job()['status'],'paused')
        self.work();self.assertEqual(self.value().wait_reason,'wt_report')
        self.action('recheck',{'condition_set_id':wt.conditions(self.value())['id']});self.start()
        with self.store.connect() as db:db.execute("UPDATE runtime_jobs SET policy='unknown' WHERE run_id=?",(self.run_id,))
        before=len(self.fixture.calls);Worker(self.service).once()
        self.assertEqual(len(self.fixture.calls),before);self.assertEqual(self.job()['status'],'blocked')

    def test_coexisting_creation_limit_and_paid_disabled(self):
        creation=self.service.create(self.owner,dict(topic='原创作',audience='测试读者',tone='清楚',material='材料',allow_hypothesis=True,mode='simulation'))
        self.assertEqual(creation['workflow_type'],'creation')
        with self.assertRaises(DomainError):self.service.create(self.owner,self.input)
        self.action('cancel')
        unconfigured=Service(self.store,Config('existing-key-must-not-be-used'))
        with self.assertRaisesRegex(DomainError,'未启用'):unconfigured.create(self.owner,self.input)
        simulated=unconfigured.create(self.owner,{**self.input,'mode':'simulation'})
        self.assertEqual(simulated['mode'],'simulation')

    def test_paid_route_cannot_hide_behind_fixture_client(self):
        from backend.model_router import Route
        from backend.workflow import digest
        self.action('cancel')
        self.service.executor.router.routes['wt_read']=Route('deepseek','deepseek-flash')
        with self.assertRaisesRegex(DomainError,'未启用'):
            self.service.create(self.owner,self.input)
        self.assertEqual(self.fixture.calls,[])
        self.service.executor.router.routes.clear()
        self.run_id=self.service.create(self.owner,self.input)['run_id']
        self.work();self.confirm()
        run=self.value()
        with self.store.connect() as db:
            policy=run.context['model_policy']
            policy['routes']['wt_read']['provider']='deepseek'
            policy['version']=digest(policy['routes'])
            from backend.runtime import Runtime
            Runtime.write(None,db,run)
        before=len(self.fixture.calls)
        self.work()
        self.assertEqual(self.job()['status'],'blocked')
        self.assertEqual(len(self.fixture.calls),before)

    def test_sigkill_process_recovers_in_postgres_or_sqlite(self):
        self.work();self.confirm();self.start()
        marker=Path(self.tmp.name)/'stopped.marker'
        root=Path(__file__).resolve().parents[1]
        env={**os.environ,'PYTHONPATH':str(root)+os.pathsep+str(root/'tests'),
             'FIXTURE_DATABASE_URL':self.store.path,'FIXTURE_OWNER':self.owner,
             'FIXTURE_MARKER':str(marker),'FIXTURE_POINT':'after_commit','PYTHONDONTWRITEBYTECODE':'1'}
        command=[sys.executable,str(root/'tests/windtunnel_process_fixture.py')]
        with tempfile.TemporaryFile() as output:
            process=subprocess.Popen(command,env=env,stdout=output,stderr=output)
            try:
                deadline=time.monotonic()+20
                while not marker.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.05)
                if not marker.exists():
                    output.seek(0);self.fail(output.read().decode())
                process.kill();process.wait(timeout=5)
            finally:
                if process.poll() is None:process.kill();process.wait()
        time.sleep(1.1)
        result=subprocess.run(command,env={**env,'FIXTURE_POINT':'none'},capture_output=True,timeout=25)
        self.assertEqual(result.returncode,0,result.stderr.decode())
        self.assertEqual(self.value().wait_reason,'wt_report',self.job())
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM live_calls WHERE run_id=? AND stage='wt_read'",(self.run_id,)).fetchone()[0],1)
        self.assertEqual(len(self.value().windtunnel['reports']),1)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'requires actual PostgreSQL')
class PostgresWindtunnelRuntimeTests(WindtunnelRuntimeTests):
    def setUp(self):
        import psycopg
        self.tmp=tempfile.TemporaryDirectory();self.schema='youji_test_'+uuid4().hex
        self.base=os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('CREATE SCHEMA '+self.schema)
        target=self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema
        self.store=Store(target);self.prepare()
    def tearDown(self):
        import psycopg
        super().tearDown()
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('DROP SCHEMA '+self.schema+' CASCADE')

    def test_concurrent_first_boot_of_api_and_worker(self):
        import psycopg
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from backend.auth import Auth
        schema='youji_test_'+uuid4().hex
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('CREATE SCHEMA '+schema)
        target=self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+schema
        barrier=threading.Barrier(4)
        def boot(index):
            barrier.wait()
            store=Store(target)
            if index%2==0:Auth(store)
            service=Service(store,Config())
            with store.connect() as db:
                return db.has_table('windtunnel_checklists') and db.has_table('live_calls')
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                self.assertEqual(list(pool.map(boot,range(4))),[True]*4)
        finally:
            with psycopg.connect(self.base,autocommit=True) as db:db.execute('DROP SCHEMA '+schema+' CASCADE')

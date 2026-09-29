"""Durable execution acceptance; test adapters never call paid models."""
import json
import os
import tempfile
import subprocess
import sys
import time
import unittest
from pathlib import Path
from uuid import uuid4
from backend.store import Store
from backend.service import Service
from backend.provider import Config
from backend.worker import Worker
from backend.contracts import DomainError
from backend.runtime import Runtime,checkpointer
from backend.demo import validate_brief
import test_live_provider as fixtures


class DurableTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'runtime.sqlite')
        self.prepare()

    def prepare(self):
        self.model=fixtures.FixtureModel();self.config=Config('test-only-never-sent')
        self.service=Service(self.store,self.config,self.model)
        self.owner='fictional-owner'
        data=dict(topic='公共资料测试',audience='虚构读者',tone='朴实',material='这是一份公开资料的测试摘要。',allow_hypothesis=True,mode='live')
        self.run_id=self.service.create(self.owner,data)['run_id']

    def tearDown(self):self.tmp.cleanup()
    def run_value(self):return self.store.get(self.run_id,self.owner)
    def start(self):
        run=self.run_value()
        return self.service.background(self.owner,self.run_id,dict(action='start',version=run.status_version,key=str(uuid4())))
    def job(self):return self.service.jobs.public(self.run_id,self.owner)
    def action(self, action, payload):
        return self.service.action(self.owner,self.run_id,dict(action=action,version=self.run_value().status_version,key=str(uuid4()),payload=payload))

    def test_independent_worker_stops_at_human_and_reaudits_edit(self):
        response=self.start();self.assertTrue(response['in_flight']);self.assertEqual(self.model.calls,[])
        # A new application/worker instance runs after the request has returned.
        independent=Service(Store(self.store.path),self.config,self.model)
        Worker(independent).once()
        run=self.run_value();self.assertEqual(run.wait_reason,'final_confirmation',self.job())
        self.assertEqual(self.job()['status'],'waiting');self.assertEqual(len(self.model.calls),8)
        old=run.drafts[-1]
        with self.assertRaises(DomainError):self.action('accept',dict(draft_ref='wrong',review_ref=run.review['ref']))
        changed=dict(old['content']);changed['body']='人工编辑后的稿件。'
        self.action('edit',changed)
        with self.assertRaises(DomainError):self.action('accept',dict(draft_ref=old['ref'],review_ref=run.review['ref']))
        self.start();Worker(independent).once()
        run=self.run_value();self.assertEqual(run.wait_reason,'final_confirmation',self.job());self.assertEqual(len(self.model.calls),9)
        self.action('accept',dict(draft_ref=run.drafts[-1]['ref'],review_ref=run.review['ref']))
        self.assertEqual(self.run_value().run_status,'SUCCEEDED')
        self.assertEqual(self.job()['status'],'done')

    def test_committed_node_replay_and_response_reuse(self):
        self.start()
        tripped=[]
        def crash(point,stage):
            if point=='after_commit' and stage=='strategy' and not tripped:
                tripped.append(True);raise RuntimeError('process stopped before checkpoint')
        Worker(self.service,fault=crash).once()
        self.assertEqual(self.job()['status'],'blocked')
        self.assertEqual(self.model.calls.count('strategy'),1)
        self.start();Worker(Service(Store(self.store.path),self.config,self.model)).once()
        self.assertEqual(self.job()['status'],'waiting',self.job())
        self.assertEqual(len(self.model.calls),8)
        self.assertEqual(len([a for a in self.run_value().artifacts if a['stage']=='strategy']),1)

    def test_received_response_reused_after_restart(self):
        self.start();tripped=[]
        def crash(point,stage):
            if point=='after_response' and stage=='outline' and not tripped:
                tripped.append(True);raise RuntimeError('response saved but node uncommitted')
        Worker(self.service,fault=crash).once();self.assertEqual(self.job()['status'],'blocked')
        self.start();Worker(self.service).once()
        self.assertEqual(self.job()['status'],'waiting',self.job());self.assertEqual(self.model.calls.count('outline'),1)

    def test_public_material_snapshot_and_audit_survive_live_fixture_graph(self):
        self.action('cancel',{})
        fixture=json.loads((Path(__file__).parent/'public_materials.json').read_text(encoding='utf-8'))['sources'][0]
        account=self.service.operations.read(self.owner)['accounts'][0]['id']
        self.service.knowledge.save(self.owner,dict(account_id=account,title=fixture['title'],text=fixture['text']),source_type='editorial_summary',source_url=fixture['url'],metadata=fixture)
        data=dict(topic='胶囊衣橱',audience='虚构读者',tone='清楚',material='',mode='live',allow_hypothesis=True,
                  operations=dict(account_id=account,platform='xiaohongshu',account='虚构账号'),knowledge={'enabled':True})
        self.run_id=self.service.create(self.owner,data)['run_id']
        self.start();Worker(self.service).once()
        self.assertEqual(self.run_value().wait_reason,'final_confirmation',self.job())
        for node in self.run_value().node_runs:
            self.assertTrue(node['input']['materials'][0]['source_id'].startswith('kb:'))
        for call in self.service.executor.public(self.run_value())['calls']:
            self.assertTrue(any(source.get('url')==fixture['url'] for source in call['sources']))
            self.assertEqual(call['snapshot_id'],self.run_value().snapshot_id)

    def test_successful_parallel_sibling_survives_other_failure(self):
        self.start()
        def crash(point,stage):
            if point=='before_call' and stage=='research':raise RuntimeError('research transport not started')
        Worker(self.service,fault=crash).once()
        self.assertIn('audience',self.run_value().branches)
        self.start();Worker(self.service).once()
        self.assertEqual(self.job()['status'],'waiting',self.job());self.assertEqual(self.model.calls.count('audience'),1)

    def test_unknown_transport_does_not_repeat_paid_call(self):
        original=self.model.complete
        def fail(messages):
            if '负责 research 的' in messages[0]['content']:
                self.model.calls.append('unknown-research');raise TimeoutError()
            return original(messages)
        self.model.complete=fail;self.start();Worker(self.service).once()
        self.assertEqual(self.job()['status'],'blocked')
        self.model.complete=original;before=len(self.model.calls)
        self.start();Worker(self.service).once()
        self.assertEqual(len(self.model.calls),before)
        self.assertIn('未知',self.job()['error'])

    def test_owner_idempotency_and_old_lease_fencing(self):
        run=self.run_value();data=dict(action='start',version=run.status_version,key='same')
        self.service.background(self.owner,self.run_id,data)
        self.service.background(self.owner,self.run_id,data)
        with self.assertRaises(DomainError):self.service.background('another',self.run_id,data)
        first=self.service.jobs.claim(1)
        with self.store.connect() as db:db.execute('UPDATE runtime_jobs SET lease_until=?',(time.time()-1,))
        second=self.service.jobs.claim(30)
        with self.store.connect() as db:
            with self.assertRaises(DomainError):self.service.jobs.guard(db,first)
        self.service.jobs.finish(first,'done')
        self.assertEqual(self.job()['status'],'running')
        Runtime(self.service,self.service.jobs,second).execute()
        self.assertEqual(self.run_value().wait_reason,'final_confirmation')

    def test_cancel_wins_late_results(self):
        self.start();tripped=[]
        def cancel(point,stage):
            if point=='after_response' and stage=='strategy' and not tripped:
                tripped.append(True);self.action('cancel',{})
        Worker(self.service,fault=cancel).once()
        self.assertEqual(self.run_value().run_status,'CANCELLED')
        self.assertFalse(self.run_value().artifacts)
        self.assertEqual(self.job()['status'],'done')
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT state FROM live_calls WHERE stage='strategy'").fetchone()[0],'validated')

    def test_pause_between_nodes_then_resume(self):
        self.start();paused=[]
        def pause(point,stage):
            if point=='after_commit' and stage=='strategy' and not paused:
                paused.append(True);r=self.run_value()
                self.service.background(self.owner,self.run_id,dict(action='pause',version=r.status_version,key='pause'))
        Worker(self.service,fault=pause).once()
        self.assertEqual(self.job()['status'],'paused',self.job());self.assertEqual(len(self.model.calls),3)
        self.start();Worker(self.service).once()
        self.assertEqual(self.job()['status'],'waiting',self.job());self.assertEqual(len(self.model.calls),8)

    def test_simulation_revision_and_supplement_use_no_models(self):
        self.action('cancel',{})
        data=dict(topic='模拟测试',audience='虚构读者',tone='清楚',material='',scenario='missing',allow_hypothesis=True)
        self.run_id=self.service.create(self.owner,data)['run_id']
        self.start();Worker(self.service).once()
        self.assertEqual(self.run_value().wait_reason,'missing_material',self.job())
        old=self.run_value().snapshot_id
        self.action('supplement',dict(material='测试补充资料',allow_hypothesis=True))
        self.start();Worker(self.service).once()
        self.assertNotEqual(old,self.run_value().snapshot_id)
        self.assertEqual(self.run_value().wait_reason,'final_confirmation',self.job())
        self.action('cancel',{})
        self.run_id=self.service.create(self.owner,{**data,'scenario':'revision'})['run_id']
        self.start();Worker(self.service).once()
        self.assertEqual(self.run_value().wait_reason,'final_confirmation',self.job())
        self.assertEqual(len(self.run_value().drafts),2)
        self.assertEqual(self.model.calls,[])

    def test_sigkill_after_response_and_commit_resumes_without_duplicate_calls(self):
        root=Path(__file__).resolve().parents[1]
        for point in ('after_response','after_commit'):
            with self.subTest(point=point):
                if self.run_value().run_status!='QUEUED':
                    self.action('cancel',{});self.prepare()
                self.start()
                marker=Path(self.tmp.name)/point
                env={**os.environ,'PYTHONPATH':str(root)+os.pathsep+str(root/'tests'),
                     'FIXTURE_DATABASE_URL':self.store.path,'FIXTURE_POINT':point,
                     'FIXTURE_STAGE':'strategy','FIXTURE_MARKER':str(marker),
                     'PYTHONDONTWRITEBYTECODE':'1'}
                with tempfile.TemporaryFile() as output:
                    process=subprocess.Popen([sys.executable,str(root/'tests/runtime_process_fixture.py')],env=env,stdout=output,stderr=output)
                    try:
                        # WSL on a Windows-mounted checkout can need more than 20s
                        # to import the worker after a forced process crash.
                        deadline=time.monotonic()+45
                        while not marker.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.05)
                        if not marker.exists():
                            output.seek(0);self.fail('worker did not reach crash point: '+output.read().decode())
                        process.kill();process.wait(timeout=5)
                    finally:
                        if process.poll() is None:process.kill();process.wait()
                # A real killed process cannot renew the persisted lease.
                time.sleep(1.1)
                with self.store.connect() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM live_calls WHERE run_id=?',(self.run_id,)).fetchone()[0],3)
                # The crash lease is deliberately one second so takeover is
                # quick.  Recovery itself uses a realistic lease: slow Windows
                # CI filesystems can hold SQLite's writer lock for over a second,
                # temporarily preventing the heartbeat thread from renewing.
                clean={**env,'FIXTURE_POINT':'none','FIXTURE_LEASE':'30'}
                result=subprocess.run([sys.executable,str(root/'tests/runtime_process_fixture.py')],env=clean,capture_output=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stderr.decode())
                self.assertEqual(self.run_value().wait_reason,'final_confirmation',self.job())
                with self.store.connect() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM live_calls WHERE run_id=?',(self.run_id,)).fetchone()[0],8)
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM runtime_nodes WHERE run_id=?',(self.run_id,)).fetchone()[0],8)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'requires actual PostgreSQL')
class PostgresDurableTests(DurableTests):
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

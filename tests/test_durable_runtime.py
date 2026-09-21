"""Durable execution acceptance; test adapters never call paid models."""
import json
import os
import tempfile
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

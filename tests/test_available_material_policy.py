"""Available evidence delivery preserves citations, accounting and manual consent."""
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from backend.api import create_app
from backend.contracts import DomainError
from backend.provider import Config
from backend.service import Service
from backend.store import Store
from backend.worker import Worker
import test_live_provider as fixtures


class GapModel(fixtures.FixtureModel):
    def complete(self,messages):
        value,tokens=super().complete(messages)
        if self.calls[-1]=='research':
            value.update(core_gap=True,gaps=['没有产品规格、价格或真实测试结果'],facts=[])
        return value,tokens


class AvailableMaterialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(str(Path(self.temp.name)/'test.sqlite'))
        self.model=GapModel();self.config=Config('offline-only')
        self.service=Service(self.store,self.config,self.model)
    def tearDown(self):self.temp.cleanup()
    def create(self):
        return self.service.create('owner',dict(topic='相机怎么选',audience='新手',tone='清楚',material='仅有产品名称，未提供规格。',allow_hypothesis=False,mode='live',web_research={'enabled':False,'queries':[]}))
    def start(self,run_id):
        current=self.store.get(run_id,'owner')
        return self.service.background('owner',run_id,dict(action='start',version=current.status_version,key=str(uuid4())))
    def legacy(self,run_id):
        with self.store.connect() as db:
            run=self.store._get(db,run_id,'owner');run.context.pop('material_policy',None)
            db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(asdict(run)),run_id))

    def test_new_gap_and_no_history_deliver_draft_without_hypothesis_or_false_approval(self):
        created=self.create();run_id=created['run_id'];self.start(run_id);Worker(self.service).once()
        run=self.store.get(run_id,'owner');view=self.service.view(run)
        self.assertEqual(run.context['material_policy'],'available_only')
        self.assertFalse(run.context['allow_hypothesis'])
        self.assertTrue(run.branches['research']['data']['core_gap'])
        self.assertEqual((run.run_status,run.wait_reason),('WAITING_USER','final_confirmation'))
        self.assertEqual(run.review['decision'],'needs_human')
        self.assertTrue(run.review['human_questions']);self.assertTrue(run.drafts)
        self.assertNotIn('accept',view['allowed_actions']);self.assertIn('adopt_manual',view['allowed_actions'])
        self.assertFalse(any(e['type']=='workflow.transition' and e['payload'].get('wait_reason') in ('missing_material','hypothesis_permission') for e in run.events))
        with self.assertRaises(DomainError):run.accept(run.drafts[-1]['ref'],run.review['ref'])
        self.assertIsNone(run.accepted_ref)
        self.assertEqual(len(self.model.calls),8)

    def test_explicit_legacy_start_preserves_analysis_snapshot_billing_and_restart(self):
        run_id=self.create()['run_id'];self.legacy(run_id);self.start(run_id);Worker(self.service).once()
        before=self.store.get(run_id,'owner')
        self.assertEqual(before.wait_reason,'hypothesis_permission')
        self.assertEqual(len(self.model.calls),2)
        with self.store.connect() as db:
            calls=[tuple(r) for r in db.execute('SELECT id,actual,response_json FROM live_calls').fetchall()]
        self.service=Service(Store(self.store.path),self.config,self.model)
        self.start(run_id);Worker(self.service).once()
        after=self.store.get(run_id,'owner')
        self.assertEqual(after.snapshot_id,before.snapshot_id)
        self.assertEqual(after.branches,before.branches)
        self.assertEqual(after.context['model_policy'],before.context['model_policy'])
        self.assertEqual(after.wait_reason,'final_confirmation')
        self.assertEqual(self.model.calls.count('audience'),1);self.assertEqual(self.model.calls.count('research'),1)
        with self.store.connect() as db:
            for call in calls:
                self.assertEqual(tuple(db.execute('SELECT id,actual,response_json FROM live_calls WHERE id=?',(call[0],)).fetchone()),call)
        self.assertEqual(after.supplements,0)

    def test_legacy_missing_material_start_skips_completed_analysis(self):
        run_id=self.create()['run_id'];self.legacy(run_id)
        with self.store.connect() as db:
            run=self.store._get(db,run_id,'owner');run.context['allow_hypothesis']=True
            db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(asdict(run)),run_id))
        self.start(run_id);Worker(self.service).once()
        self.assertEqual(self.store.get(run_id,'owner').wait_reason,'missing_material')
        self.start(run_id);Worker(self.service).once()
        self.assertEqual(self.store.get(run_id,'owner').wait_reason,'final_confirmation')
        self.assertEqual(self.model.calls.count('research'),1)
        self.assertEqual(len(self.model.calls),8)

    def test_existing_review_wait_converts_to_final_without_model_call(self):
        run_id=self.create()['run_id'];self.start(run_id);Worker(self.service).once()
        with self.store.connect() as db:
            run=self.store._get(db,run_id,'owner')
            run.context.pop('material_policy',None);run.wait_reason='missing_material'
            db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(asdict(run)),run_id))
        before=self.store.get(run_id,'owner');calls=list(self.model.calls)
        self.start(run_id)
        after=self.store.get(run_id,'owner')
        self.assertEqual(after.wait_reason,'final_confirmation')
        self.assertEqual(after.review,before.review)
        self.assertEqual(after.context['model_policy'],before.context['model_policy'])
        self.assertEqual(after.drafts,before.drafts)
        self.assertEqual(self.model.calls,calls)
        self.assertEqual(self.service.jobs.public(run_id,'owner')['status'],'waiting')

    def test_http_create_background_final_manual_gate(self):
        with patch('backend.api.settings',return_value={}):
            app=create_app(self.store,self.config,origin='http://testserver',invite='',client=self.model)
        with TestClient(app) as client:
            csrf=client.get('/api/session').json()['csrf']
            def post(path,payload):return client.post(path,json=payload,headers={'Origin':'http://testserver','X-CSRF-Token':csrf})
            registered=post('/api/auth/register',{'username':'available_material','password':'Test-long-password'})
            csrf=registered.json()['csrf']
            created=post('/api/runs',dict(topic='相机怎么选',audience='新手',tone='清楚',material='只提供名称',allow_hypothesis=False,mode='live',web_research={'enabled':False,'queries':[]}))
            self.assertEqual(created.status_code,201,created.text)
            run=created.json();path='/api/runs/'+run['run_id']
            response=post(path+'/background',dict(action='start',version=run['status_version'],key=str(uuid4())))
            self.assertEqual(response.status_code,202,response.text)
            Worker(app.state.service).once()
            final=client.get(path).json()
            self.assertEqual(final['wait_reason'],'final_confirmation')
            self.assertNotIn('accept',final['allowed_actions'])
            self.assertIn('adopt_manual',final['allowed_actions'])
            self.assertEqual(final['review']['decision'],'needs_human')
            self.assertIsNone(final['accepted_ref'])

"""Offline regeneration preserves history, budgets and explicit network choice."""
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from backend.contracts import DomainError
from backend.provider import Config
from backend.service import Service
from backend.store import Store
from backend.worker import Worker
from test_live_provider import FixtureModel


class ResearchRegenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(str(Path(self.temp.name)/'test.sqlite'))
        self.model=FixtureModel()
        self.service=Service(self.store,Config('offline-fixture-only'),self.model)
        self.owner='owner'

    def tearDown(self):self.temp.cleanup()

    def create(self, **changes):
        data=dict(topic='相机怎么选',audience='新手',tone='清楚',material='选择适合拍摄需求的相机。',
                  allow_hypothesis=True,mode='live',web_research={'enabled':False,'queries':[]})
        data.update(changes)
        return self.service.create(self.owner,data)

    def prepared(self):
        created=self.create()
        self.service.background(self.owner,created['run_id'],dict(action='start',version=created['status_version'],key=str(uuid4())))
        Worker(self.service).once()
        run=self.store.get(created['run_id'],self.owner)
        self.assertTrue(run.drafts)
        self.assertEqual(run.run_status,'WAITING_USER')
        return run

    def save(self, run):
        with self.store.connect() as db:
            db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(asdict(run)),run.run_id))

    def command(self, run, key=None):
        return dict(action='research_and_regenerate',version=run.status_version,key=key or str(uuid4()))

    def ledger(self, run_id):
        with self.store.connect() as db:
            calls=[tuple(row) for row in db.execute('SELECT * FROM live_calls WHERE run_id=? ORDER BY id',(run_id,)).fetchall()]
            lineage=[tuple(row) for row in db.execute('SELECT * FROM live_lineage WHERE run_id=?',(run_id,)).fetchall()]
        return calls,lineage

    def test_existing_draft_research_reset_preserves_history_budget_and_iteration(self):
        before=self.prepared();before.iteration=2;self.save(before)
        ledger=self.ledger(before.run_id);model_calls=list(self.model.calls)
        self.service.background(self.owner,before.run_id,self.command(before))
        after=self.store.get(before.run_id,self.owner)
        self.assertNotEqual(after.snapshot_id,before.snapshot_id)
        self.assertEqual(after.current_stage,'brief')
        self.assertEqual(after.branches,{})
        self.assertEqual(after.artifacts,[])
        self.assertIsNone(after.review)
        self.assertIsNone(after.prior_review)
        self.assertIsNone(after.wait_reason)
        self.assertIn(after.run_status,('QUEUED','RUNNING'))
        for field in ('drafts','reviews','node_runs','iteration'):
            self.assertEqual(getattr(after,field),getattr(before,field),field)
        self.assertEqual(after.context['model_policy'],before.context['model_policy'])
        self.assertEqual(self.ledger(before.run_id),ledger)
        self.assertEqual(self.model.calls,model_calls)
        self.assertTrue(after.context['web_research']['enabled'])
        self.assertEqual(after.context['web_research']['status'],'pending')
        archive=after.context['research_regenerations']
        self.assertEqual(len(archive),1)
        self.assertIn(before.snapshot_id,json.dumps(archive))

    def test_same_key_and_old_version_is_idempotent(self):
        before=self.prepared();command=self.command(before,'same-key')
        self.service.background(self.owner,before.run_id,command)
        first=asdict(self.store.get(before.run_id,self.owner))
        self.service.background(self.owner,before.run_id,command)
        self.assertEqual(asdict(self.store.get(before.run_id,self.owner)),first)

    def test_worker_regeneration_uses_new_snapshot_and_retains_old_draft(self):
        before=self.prepared();old_calls=self.ledger(before.run_id)[0]
        self.service.background(self.owner,before.run_id,self.command(before))
        queued=self.store.get(before.run_id,self.owner)
        source={'source_id':'web:fixture','source_type':'web','title':'相机怎么选',
                'url':'https://example.org/camera','text':'相机怎么选：按拍摄需求比较便携性与握持感。',
                'verification':'离线测试替身，非真实联网证据','body_read':True,'model_match':'exact'}
        report={'status':'complete','queries':['相机怎么选'],'sources':[source],
                'searches':[],'reads':[{'url':source['url'],'status':'read'}],
                'searched_at':'2026-10-12T00:00:00+00:00','limitation':'离线替身'}
        with patch('backend.web_research.collect',return_value=report) as collect:
            self.assertTrue(Worker(self.service).once())
        collect.assert_called_once()
        after=self.store.get(before.run_id,self.owner)
        self.assertEqual((after.run_status,after.wait_reason),('WAITING_USER','final_confirmation'))
        self.assertEqual(after.snapshot_id,queued.snapshot_id)
        self.assertEqual(after.drafts[:len(before.drafts)],before.drafts)
        self.assertEqual(len(after.drafts),len(before.drafts)+1)
        self.assertEqual(after.drafts[-1]['snapshot_id'],after.snapshot_id)
        self.assertEqual(after.node_runs[:len(before.node_runs)],before.node_runs)
        fresh=after.node_runs[len(before.node_runs):]
        self.assertEqual(len(fresh),8)
        self.assertTrue(all(node['snapshot_id']==after.snapshot_id for node in fresh))
        self.assertTrue(all(node['input']['web_research']['status']=='complete' for node in fresh))
        self.assertTrue(all(any(item['source_id']=='web:fixture' for item in node['input']['materials']) for node in fresh))
        latest={row[0]:row for row in self.ledger(before.run_id)[0]}
        for old in old_calls:self.assertEqual(latest[old[0]],old)
        self.assertEqual(len(self.model.calls),16)

    def test_bounded_failed_usage_keeps_reservations_and_completes_fresh_pipeline(self):
        original=self.prepared
        def with_unknown():
            run=original()
            with self.store.connect() as db:
                for stage in ('audience','research'):
                    call=db.execute('SELECT id FROM live_calls WHERE run_id=? AND stage=?',(run.run_id,stage)).fetchone()[0]
                    unknown='unknown-'+stage
                    db.execute("INSERT INTO live_calls(id,run_id,agent,stage,reserved,state,error) SELECT ?,run_id,agent,stage,40000,'failed','transport interrupted' FROM live_calls WHERE id=?",(unknown,call))
                    columns=[name for name in db.columns('model_audit') if name!='call_id']
                    names=','.join(columns)
                    db.execute(f'INSERT INTO model_audit(call_id,{names}) SELECT ?,{names} FROM model_audit WHERE call_id=?',(unknown,call))
                    db.execute("UPDATE model_audit SET outcome='failed',rate=0.0000002 WHERE call_id=?",(unknown,))
            return run
        self.prepared=with_unknown
        self.test_worker_regeneration_uses_new_snapshot_and_retains_old_draft()
        with self.store.connect() as db:
            rows=db.execute("SELECT actual,reserved,state FROM live_calls WHERE stage IN ('audience','research') AND state='failed'").fetchall()
        self.assertEqual([tuple(row) for row in rows],[(None,40000,'failed')]*2)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM live_calls WHERE state!='not_sent'").fetchone()[0],18)


    def test_unknown_with_unbounded_price_cannot_restart(self):
        before=self.prepared()
        with self.store.connect() as db:
            db.execute("UPDATE live_calls SET actual=NULL,state='failed' WHERE run_id=? AND stage='research'",(before.run_id,))
            db.execute("UPDATE model_audit SET rate=? WHERE run_id=? AND stage='research'",(float('inf'),before.run_id))
        ledger=self.ledger(before.run_id)
        with self.assertRaises(DomainError) as caught:
            self.service.background(self.owner,before.run_id,self.command(before))
        self.assertEqual(caught.exception.code,'USAGE_UNKNOWN')
        self.assertEqual(self.ledger(before.run_id),ledger)

    def test_running_existing_draft_can_request_new_research(self):
        before=self.prepared();before.run_status='RUNNING';before.wait_reason=None;self.save(before)
        self.service.background(self.owner,before.run_id,self.command(before))
        self.assertEqual(self.store.get(before.run_id,self.owner).current_stage,'brief')

    def test_legacy_material_and_hypothesis_waits_without_draft_can_restart(self):
        before=self.prepared()
        for reason in ('missing_material','hypothesis_permission'):
            with self.subTest(reason=reason):
                before=self.store.get(before.run_id,self.owner)
                before.run_status='WAITING_USER';before.wait_reason=reason
                before.drafts=[];before.review=None;before.current_stage='brief';self.save(before)
                self.service.background(self.owner,before.run_id,self.command(before))
                after=self.store.get(before.run_id,self.owner)
                self.assertNotEqual(after.snapshot_id,before.snapshot_id)
                self.assertIsNone(after.wait_reason)
                # Reset inactive job status to isolate the next eligibility case.
                with self.store.connect() as db:
                    db.execute("UPDATE runtime_jobs SET status='waiting' WHERE run_id=?",(before.run_id,))

    def test_terminal_simulation_active_and_unknown_usage_are_rejected(self):
        base=self.prepared()
        variants=[('status',value) for value in ('SUCCEEDED','FAILED','CANCELLED','EXPIRED')]
        variants += [('mode','simulation')]+[('job',value) for value in ('queued','running','pausing')]+[('usage','unknown')]
        for kind,value in variants:
            with self.subTest(kind=kind,value=value):
                self.save(base)
                with self.store.connect() as db:
                    db.execute("UPDATE runtime_jobs SET status='waiting' WHERE run_id=?",(base.run_id,))
                    db.execute("DELETE FROM live_calls WHERE id='unknown-test'")
                before=self.store.get(base.run_id,self.owner)
                if kind=='status':before.run_status=value
                elif kind=='mode':before.context['mode']=value
                elif kind=='job':
                    with self.store.connect() as db:
                        db.execute('UPDATE runtime_jobs SET status=? WHERE run_id=?',(value,base.run_id))
                elif kind=='usage':
                    with self.store.connect() as db:
                        db.execute('INSERT INTO live_calls(id,run_id,agent,stage,reserved,state) VALUES(?,?,?,?,?,?)',
                                   ('unknown-test',base.run_id,'research','research',100,'calling'))
                self.save(before);snapshot=asdict(before);ledger=self.ledger(base.run_id)
                with self.assertRaises(DomainError) as raised:
                    self.service.background(self.owner,base.run_id,self.command(before))
                expected={'job':'JOB_ACTIVE','usage':'USAGE_UNKNOWN'}.get(kind,'INVALID_TRANSITION')
                self.assertEqual(raised.exception.code,expected)
                self.assertEqual(asdict(self.store.get(base.run_id,self.owner)),snapshot)
                self.assertEqual(self.ledger(base.run_id),ledger)

    def test_create_live_defaults_topic_search_but_explicit_off_is_preserved(self):
        topic='相机推荐与真实参数核对'*7
        data=dict(topic=topic,audience='新手',tone='清楚',material='参考资料',allow_hypothesis=True,mode='live')
        created=self.service.create(self.owner,data)
        web=self.store.get(created['run_id'],self.owner).context['web_research']
        self.assertTrue(web['enabled']);self.assertEqual(web['queries'],[topic[:120]])
        self.assertEqual(web['provider'],'bing')
        self.owner='another-owner'
        disabled=self.create()
        self.assertFalse(self.store.get(disabled['run_id'],self.owner).context['web_research']['enabled'])

    def test_simulation_does_not_enable_implicit_web_research(self):
        created=self.service.create(self.owner,dict(topic='相机推荐',audience='新手',tone='清楚',material='参考资料',mode='simulation'))
        self.assertFalse(self.store.get(created['run_id'],self.owner).context['web_research']['enabled'])

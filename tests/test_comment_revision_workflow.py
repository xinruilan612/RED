"""Unpaid fixtures: opt-in public comments and version-bound user revisions."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from backend.comment_feedback import freeze, redact
from backend.contracts import DomainError
from backend.live import messages_for
from backend.operations import Operations
from backend.provider import Config
from backend.service import Service
from backend.store import Store
from backend.worker import Worker
from backend.xhs_sync import XHSSync
from test_live_provider import FixtureModel
from test_xhs_sync import Fake


class RevisionModel(FixtureModel):
    def __init__(self):
        super().__init__(); self.inputs=[]
    def complete(self, messages):
        value, tokens=super().complete(messages)
        data=json.loads(messages[1]['content']); self.inputs.append((self.calls[-1],data))
        if self.calls[-1]=='revise':
            value['body']='调整后的完整正文。'
        return value,tokens


class CommentRevisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'comments.sqlite');self.prepare()
    def prepare(self):
        self.owner='owner';self.model=RevisionModel();self.service=Service(self.store,Config('fixture-never-sent'),self.model)
        self.account=Operations(self.store).read(self.owner)['accounts'][0]['id'];self.fake=Fake()
        self.fake.result['notes'][0]['comments'][0]['content']='30ml 能用多久？联系 a@example.com 或 13812345678 @昵称'
        self.sync=XHSSync(self.store,lambda port:self.fake);self.sync.bind(self.owner,self.account);self.sync.once()
    def tearDown(self):self.tmp.cleanup()
    def create(self, feedback=None):
        data={'mode':'live','topic':'产品使用问题','audience':'读者','tone':'清楚','material':'产品容量30ml。',
              'knowledge':{'enabled':False,'automatic_references':False},
              'operations':{'account_id':self.account,'platform':'xiaohongshu'}}
        if feedback is not None:data['comment_feedback']=feedback
        result=self.service.create(self.owner,data);self.run_id=result['run_id'];return result
    def current(self):return self.store.get(self.run_id,self.owner)
    def run_worker(self):
        self.service.background(self.owner,self.run_id,{'action':'start','key':str(uuid4()),'version':self.current().status_version})
        self.assertTrue(Worker(self.service).once())
        return self.current()
    def revision_command(self,instruction='把开头改短一点'):
        run=self.current();draft=run.drafts[-1]
        return {'action':'request_revision','version':run.status_version,'key':str(uuid4()),
                'payload':{'draft_ref':draft['ref'],'content_hash':draft['content_hash'],'instruction':instruction}}
    def make_private(self):
        with self.store.connect() as db:
            row=db.execute("SELECT payload FROM xhs_sync_entities WHERE owner=? AND account_id=? AND kind='creator_account' AND id='snapshot'",(self.owner,self.account)).fetchone()
            source=json.loads(row[0]);source['notes'][0]['visibility']='private'
            db.execute("UPDATE xhs_sync_entities SET payload=? WHERE owner=? AND account_id=? AND kind='creator_account' AND id='snapshot'",(json.dumps(source),self.owner,self.account))

    def test_disabled_never_reads_comments_or_sends_them(self):
        with patch('backend.comment_feedback.XHSSync.require_public_note',side_effect=AssertionError('disabled')):
            self.create();run=self.run_worker()
        self.assertEqual(run.wait_reason,'final_confirmation')
        self.assertTrue(all('comment_feedback' not in data for _,data in self.model.inputs))

    def test_optin_freezes_redacted_samples_for_all_roles_and_audit(self):
        self.create({'enabled':True,'note_ids':['n']});snapshot=copy.deepcopy(self.current().context['comment_feedback'])
        with self.store.connect() as db:
            db.execute("UPDATE xhs_sync_entities SET payload=? WHERE owner=? AND account_id=? AND kind='comment'",(json.dumps({'id':'c','note_id':'n','content':'后来的变化'}),self.owner,self.account))
        run=self.run_worker();self.assertEqual(run.wait_reason,'final_confirmation')
        self.assertEqual(run.context['comment_feedback'],snapshot)
        self.assertEqual(snapshot['sample_size'],1);self.assertIn('30ml',snapshot['samples'][0]['text'])
        self.assertNotIn('13812345678',str(snapshot));self.assertNotIn('a@example.com',str(snapshot));self.assertNotIn('SENSITIVE_NICKNAME',str(snapshot))
        for stage,data in self.model.inputs:self.assertEqual(data['comment_feedback'],snapshot,stage)
        with self.store.connect() as db:
            rows=db.execute('SELECT sources FROM model_audit WHERE run_id=?',(self.run_id,)).fetchall()
        self.assertTrue(all(any(s.get('id')=='comment-feedback' for s in json.loads(r[0])) for r in rows))

    def test_false_payload_and_foreign_private_selection_rejected(self):
        for selection in ({'enabled':True,'note_ids':['n'],'samples':[{'text':'伪造'}]},
                          {'enabled':False,'note_ids':['n']},{'enabled':True,'note_ids':[]},
                          {'enabled':True,'note_ids':['n','n']}):
            with self.subTest(selection=selection),self.assertRaises(DomainError):freeze(self.store,self.owner,self.account,selection)
        with self.assertRaises(DomainError):freeze(self.store,'other',self.account,{'enabled':True,'note_ids':['n']})
        self.make_private()
        with self.assertRaises(DomainError):freeze(self.store,self.owner,self.account,{'enabled':True,'note_ids':['n']})

    def test_empty_comments_are_explicit_not_fabricated(self):
        with self.store.connect() as db:db.execute("DELETE FROM xhs_sync_entities WHERE owner=? AND kind='comment'",(self.owner,))
        self.create({'enabled':True,'note_ids':['n']});feedback=self.current().context['comment_feedback']
        self.assertEqual(feedback['sample_size'],0);self.assertEqual(feedback['samples'],[]);self.assertIn('不代表',feedback['limitation'])

    def test_visibility_withdrawal_stops_before_paid_reservation(self):
        self.create({'enabled':True,'note_ids':['n']})
        self.service.background(self.owner,self.run_id,{'action':'start','key':str(uuid4()),'version':self.current().status_version})
        self.make_private();Worker(self.service).once()
        self.assertEqual(self.model.calls,[])
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM live_calls WHERE run_id=?',(self.run_id,)).fetchone()[0],0)

    def test_visibility_change_between_snapshot_and_creation_leaves_no_active_run(self):
        original=freeze
        def revoke(*args):
            result=original(*args);self.make_private();return result
        with patch('backend.comment_feedback.freeze',side_effect=revoke),self.assertRaises(DomainError):
            self.create({'enabled':True,'note_ids':['n']})
        self.assertEqual(self.store.list_runs(self.owner),[])

    def test_user_revision_keeps_old_version_review_and_budget(self):
        self.create({'enabled':True,'note_ids':['n']});run=self.run_worker();old=copy.deepcopy(run.drafts[0]);snapshot=run.snapshot_id
        command=self.revision_command();result=self.service.action(self.owner,self.run_id,command)
        repeated=self.service.action(self.owner,self.run_id,command)
        self.assertEqual(result['status_version'],repeated['status_version']);self.assertIsNone(self.current().review)
        self.assertEqual(self.current().prior_review['issues'],[])
        run=self.run_worker();self.assertEqual(run.wait_reason,'final_confirmation')
        self.assertEqual(run.drafts[0],old);self.assertEqual(run.snapshot_id,snapshot);self.assertEqual(run.iteration,1)
        self.assertEqual(run.context['revision_requests'][0]['result_draft_ref'],run.drafts[-1]['ref'])
        revised=next(data for stage,data in self.model.inputs if stage=='revise')
        self.assertEqual(revised['user_revision_request']['instruction'],'把开头改短一点')
        self.assertEqual(revised['previous_review']['issues'],[])
        self.assertEqual(len(self.model.calls),10)
        self.assertEqual(self.service.view(run)['usage']['model_calls'],10)
        self.assertFalse(run.context.get('pending_revision'))

    def test_stale_revision_unknown_payload_and_inflight_rejected(self):
        self.create();self.run_worker();command=self.revision_command();command['payload']['draft_ref']='stale'
        with self.assertRaises(DomainError):self.service.action(self.owner,self.run_id,command)
        command=self.revision_command();command['payload']['unexpected']=True
        with self.assertRaises(DomainError):self.service.action(self.owner,self.run_id,command)
        self.service.action(self.owner,self.run_id,self.revision_command())
        self.service.background(self.owner,self.run_id,{'action':'start','key':str(uuid4()),'version':self.current().status_version})
        with self.assertRaises(DomainError):self.service.action(self.owner,self.run_id,self.revision_command('不要覆盖在途稿'))

    def test_two_user_revisions_do_not_reset_limits(self):
        self.create();self.run_worker()
        for i in range(2):
            self.service.action(self.owner,self.run_id,self.revision_command('调整要求'+str(i)));self.run_worker()
        self.assertEqual(len(self.model.calls),12);self.assertEqual(self.current().iteration,2)
        with self.assertRaises(DomainError):self.service.action(self.owner,self.run_id,self.revision_command('第三次'))
        self.assertNotIn('request_revision',self.service.view(self.current())['allowed_actions'])

    def test_cancel_discards_pending_revision_execution(self):
        self.create();self.run_worker();self.service.action(self.owner,self.run_id,self.revision_command())
        run=self.current();self.service.action(self.owner,self.run_id,{'action':'cancel','version':run.status_version,'key':str(uuid4()),'payload':{}})
        self.assertEqual(self.current().run_status,'CANCELLED');self.assertEqual(len(self.model.calls),8)

    def test_redaction_preserves_product_numbers_units_and_links(self):
        text='容量 30ml，售价129元 https://example.com/item/123，请问怎么用？'
        self.assertEqual(redact(text),text)

    def test_snapshot_caps_comment_context_before_model_budget(self):
        self.fake.result['notes'][0]['comments']=[{'id':str(i),'content':'请问产品使用条件？'*100} for i in range(70)]
        with self.store.connect() as db:db.execute('UPDATE xhs_sync_links SET next_at=0')
        self.sync.once();snapshot=freeze(self.store,self.owner,self.account,{'enabled':True,'note_ids':['n']})
        self.assertLessEqual(snapshot['sample_size'],50)
        self.assertLessEqual(sum(len(s['text']) for s in snapshot['samples']),4000)
        self.assertEqual(snapshot['coverage'],'historically_observed_not_complete')

    def test_comment_quotes_are_audience_evidence_not_product_facts(self):
        from backend.live import normalize,schema
        self.create({'enabled':True,'note_ids':['n']});run=self.current();sample=run.context['comment_feedback']['samples'][0]
        audience=schema('audience');audience['observations']=[{'source_id':sample['source_id'],'quote':sample['text'],'interpretation':'样本询问使用时间，不是功效证据'}]
        self.assertEqual(normalize(run,'audience',audience)['observations'][0]['quote'],sample['text'])
        research=schema('research');research['facts']=[{'source_id':sample['source_id'],'quote':sample['text']}]
        with self.assertRaises(DomainError):normalize(run,'research',research)

    def test_supplement_keeps_frozen_comments_and_does_not_resample(self):
        original=self.model.complete
        def missing_once(messages):
            value,tokens=original(messages)
            if self.model.calls[-1]=='research' and self.model.calls.count('research')==1:
                value.update(core_gap=True,gaps=['需要补充使用步骤'])
            return value,tokens
        self.model.complete=missing_once;self.create({'enabled':True,'note_ids':['n']})
        run=self.run_worker();self.assertEqual(run.wait_reason,'missing_material');old=copy.deepcopy(run.context['comment_feedback'])
        with patch('backend.comment_feedback.freeze',side_effect=AssertionError('must not resample')):
            self.service.action(self.owner,self.run_id,{'action':'supplement','version':run.status_version,'key':str(uuid4()),'payload':{'material':'产品容量30ml。使用步骤：打开瓶盖。','allow_hypothesis':True}})
            self.run_worker()
        self.assertEqual(self.current().context['comment_feedback'],old)

    def test_cancellation_after_revision_response_discards_new_draft(self):
        self.create();self.run_worker();old=copy.deepcopy(self.current().drafts)
        self.service.action(self.owner,self.run_id,self.revision_command())
        self.service.background(self.owner,self.run_id,{'action':'start','key':str(uuid4()),'version':self.current().status_version})
        def cancel(point,stage):
            if point=='after_response' and stage=='revise':
                run=self.current();self.service.action(self.owner,self.run_id,{'action':'cancel','version':run.status_version,'key':str(uuid4()),'payload':{}})
        Worker(self.service,fault=cancel).once()
        self.assertEqual(self.current().run_status,'CANCELLED');self.assertEqual(self.current().drafts,old)
        self.assertEqual(self.current().context['revision_requests'][0]['status'],'cancelled')

    def test_http_revision_uses_existing_owner_and_csrf_guarded_action_route(self):
        from fastapi.testclient import TestClient
        from backend.api import create_app
        isolated=Store(Path(self.tmp.name)/'http.sqlite');model=RevisionModel()
        with patch('backend.api.settings',return_value={}):app=create_app(isolated,Config('fixture-never-sent'),origin='http://testserver',invite='',client=model)
        with TestClient(app) as client:
            csrf=client.get('/api/session').json()['csrf']
            def post(url,data):return client.post(url,json=data,headers={'Origin':'http://testserver','X-CSRF-Token':csrf})
            response=post('/api/auth/register',{'username':'revision_http','password':'Test-long-password'})
            self.assertEqual(response.status_code,200,response.text);csrf=response.json()['csrf']
            data=post('/api/runs',{'topic':'产品资料','audience':'读者','tone':'清楚','material':'容量30ml。','mode':'live','knowledge':{'enabled':False,'automatic_references':False},'comment_feedback':{'enabled':False}}).json()
            path='/api/runs/'+data['run_id']
            self.assertEqual(post(path+'/background',{'action':'start','version':data['status_version'],'key':str(uuid4())}).status_code,202)
            Worker(app.state.service).once();data=client.get(path).json();draft=data['drafts'][-1]
            command={'action':'request_revision','version':data['status_version'],'key':str(uuid4()),'payload':{'draft_ref':draft['ref'],'content_hash':draft['content_hash'],'instruction':'语气自然一点'}}
            self.assertEqual(client.post(path+'/actions',json=command).status_code,403)
            response=post(path+'/actions',command);self.assertEqual(response.status_code,200,response.text);data=response.json()
            self.assertEqual(post(path+'/background',{'action':'start','version':data['status_version'],'key':str(uuid4())}).status_code,202)
            Worker(app.state.service).once();result=client.get(path).json()
            self.assertEqual(result['wait_reason'],'final_confirmation');self.assertEqual(len(result['drafts']),2)
            self.assertEqual(len(model.calls),10)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'requires actual PostgreSQL')
class PostgresCommentRevisionTests(CommentRevisionTests):
    def setUp(self):
        import psycopg
        self.tmp=tempfile.TemporaryDirectory();self.schema='youji_comment_revision_'+uuid4().hex;self.base=os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('CREATE SCHEMA '+self.schema)
        self.store=Store(self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema);self.prepare()
    def tearDown(self):
        import psycopg
        self.tmp.cleanup()
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('DROP SCHEMA '+self.schema+' CASCADE')

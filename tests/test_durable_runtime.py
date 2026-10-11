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

    def step(self, action='step', **extra):
        return self.service.background(self.owner,self.run_id,dict(action=action,version=self.run_value().status_version,key=str(uuid4()),**extra))

    def invalid_citation_review(self):
        base=self.model.complete
        def invalid(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='review' and self.model.calls.count('review')==1:
                value['claim_map']=[{'excerpt':'完整正文','source_id':'user-material','quote':'published_at: null'},
                    {'excerpt':'完整正文','source_id':'user-material','quote':'公开资料'}]
            return value,tokens
        self.model.complete=invalid
        self.start();Worker(self.service).once()
        self.assertEqual(self.job()['status'],'blocked')
        self.assertEqual(self.run_value().current_stage,'reviewer')

    def test_creator_notes_stop_for_human_without_rewriting_or_extra_model_calls(self):
        base=self.model.complete
        def notes(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='body':
                value['body']='素材里没有更细的权威顺序依据，我先不下定论。后续找到可标注来源，再补一版拆解。'
            return value,tokens
        self.model.complete=notes
        self.start();Worker(self.service).once()
        run=self.run_value()
        self.assertEqual(run.run_status,'WAITING_USER')
        self.assertEqual(run.wait_reason,'missing_material')
        self.assertEqual(run.review['decision'],'needs_human')
        self.assertEqual(len(self.model.calls),8)
        self.assertIn('素材里没有',run.drafts[-1]['content']['body'])
        self.assertTrue(any(i['issue_id'].startswith('copy-boundary-') for i in run.review['issues']))
        with self.store.connect() as db:
            raw=db.execute("SELECT response_json FROM live_calls WHERE run_id=? AND stage='review'",(run.run_id,)).fetchone()[0]
        self.assertEqual(json.loads(raw)['decision'],'approved')
        self.assertIn('adopt_manual',self.service.view(run)['allowed_actions'])

    def test_original_known_facts_editorial_leakage_revises_and_reaudits(self):
        from test_original_creation_http import RoutingVectors
        self.action('cancel',{})
        account=self.service.operations.read(self.owner)['accounts'][0]['id']
        self.service.knowledge.embedding_provider=RoutingVectors()
        self.service.knowledge.save(self.owner,dict(account_id=account,title='公共资料测试',
            text='公共资料测试：公开资料包含三项说明。',
            classification=dict(domains=['general'],channel='any',format='any',material_type='fact')))
        self.run_id=self.service.create(self.owner,dict(topic='公共资料测试',audience='读者',tone='清楚',
            material='公开资料包含三项说明。',allow_hypothesis=True,mode='live',
            creation=dict(domains=['general'],channel='xiaohongshu',format='note'),
            knowledge=dict(enabled=True,automatic_references=False),
            operations=dict(account_id=account,platform='xiaohongshu',account='测试账号')))['run_id']
        base=self.model.complete
        def leaked_once(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='body':value['body']='素材里没有更细依据，后续找到来源再补一版。'
            if self.model.calls[-1]=='revise':value.update(selected_title='候选一',body='公开资料包含三项说明。')
            return value,tokens
        self.model.complete=leaked_once
        self.start();Worker(self.service).once()
        run=self.run_value()
        self.assertEqual(run.wait_reason,'final_confirmation',self.job())
        self.assertEqual(len(run.drafts),2)
        self.assertEqual(self.model.calls.count('revise'),1)
        self.assertEqual(self.model.calls.count('review'),2)
        self.assertEqual(len(self.model.calls),10)
        first_review=next(n['output'] for n in run.node_runs if n['stage']=='review')
        self.assertEqual(first_review['decision'],'revision_required')
        self.assertTrue(any(i['issue_id'].startswith('copy-boundary-') for i in first_review['issues']))
        self.assertEqual(first_review['human_questions'],[])
        self.assertTrue(all(i['result']=='resolved' for i in run.review['previous_issue_results']))
        self.assertEqual(run.drafts[-1]['content']['body'],'公开资料包含三项说明。')

    def test_received_analysis_id_typo_replays_free_and_keeps_raw_audit(self):
        from unittest.mock import patch
        base=self.model.complete
        def typo(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='audience':
                value['observations']=[{'source_id':'usermaterial','quote':'这是一份公开资料的测试摘要。','interpretation':'原文观察'}]
            return value,tokens
        self.model.complete=typo
        # Simulate the older validator rejecting the already-paid response.
        with patch('backend.citation_ids.repair',side_effect=lambda stage,value,sources:(value,[])):
            self.start();Worker(self.service).once()
        self.assertEqual(self.job()['status'],'blocked')
        self.assertEqual(self.model.calls.count('audience'),1)
        self.start();Worker(self.service).once()
        run=self.run_value()
        self.assertEqual(run.wait_reason,'final_confirmation')
        self.assertEqual(self.model.calls.count('audience'),1)
        self.assertEqual(len(self.model.calls),8)
        node=next(n for n in run.node_runs if n['stage']=='audience')
        self.assertEqual(node['citation_repairs'][0]['to'],'user-material')
        self.assertEqual(node['output']['observations'][0]['source_id'],'user-material')
        with self.store.connect() as db:
            raw=db.execute("SELECT response_json FROM live_calls WHERE run_id=? AND stage='audience'",(run.run_id,)).fetchone()[0]
        self.assertEqual(json.loads(raw)['observations'][0]['source_id'],'usermaterial')

    def test_received_six_titles_replays_without_extra_call_and_keeps_raw_response(self):
        from unittest.mock import patch
        base=self.model.complete
        def surplus(messages):
            value,tokens=base(messages)
            stage=self.model.calls[-1]
            if stage=='title':
                value['candidates']=['标题'+str(i) for i in range(6)]
                value['reasons']=['理由'+str(i) for i in range(6)]
                value['selected']='标题5'
            if stage=='body':value['selected_title']=json.loads(messages[1]['content'])['upstream']['title']['selected']
            return value,tokens
        self.model.complete=surplus
        with patch('backend.live.bounded_title_candidates',side_effect=lambda run,value:(value,None)):
            self.start();Worker(self.service).once()
        self.assertEqual(self.job()['status'],'blocked')
        self.assertEqual(self.model.calls.count('title'),1)
        self.assertFalse(self.run_value().drafts)
        self.start();Worker(self.service).once()
        run=self.run_value()
        self.assertEqual(run.wait_reason,'final_confirmation',self.job())
        self.assertEqual(self.model.calls.count('title'),1)
        self.assertEqual(len(self.model.calls),8)
        title=next(n for n in run.node_runs if n['stage']=='title')
        self.assertEqual(title['output']['candidates'],['标题0','标题1','标题2','标题3','标题5'])
        self.assertEqual(title['output']['reasons'],['理由0','理由1','理由2','理由3','理由5'])
        self.assertEqual(title['output_normalizations'][0]['kept_indices'],[0,1,2,3,5])
        with self.store.connect() as db:
            raw=db.execute("SELECT response_json,state FROM live_calls WHERE run_id=? AND stage='title'",(run.run_id,)).fetchall()
        self.assertEqual(len(raw),1)
        self.assertEqual(raw[0][1],'validated')
        self.assertEqual(json.loads(raw[0][0])['candidates'],['标题'+str(i) for i in range(6)])
        self.assertEqual(json.loads(raw[0][0])['reasons'],['理由'+str(i) for i in range(6)])

    def test_unmatched_analysis_quote_stays_blocked_without_extra_call(self):
        base=self.model.complete
        def invalid(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='audience':
                value['observations']=[{'source_id':'usermaterial','quote':'不存在的原文','interpretation':'观察'}]
            return value,tokens
        self.model.complete=invalid
        self.start();Worker(self.service).once()
        self.assertEqual(self.job()['status'],'blocked')
        before=len(self.model.calls)
        self.start();Worker(self.service).once()
        self.assertEqual(self.job()['status'],'blocked')
        self.assertEqual(len(self.model.calls),before)
        self.assertFalse(self.run_value().drafts)

    def test_review_outer_whitespace_recovers_without_new_model_call(self):
        from unittest.mock import patch
        base=self.model.complete
        def padded(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='review':
                value['claim_map']=[{'source_id':'user-material','quote':' 这是一份公开资料的测试摘要。 ','excerpt':'完整正文'}]
            return value,tokens
        self.model.complete=padded
        with patch('backend.citation_ids.repair',side_effect=lambda stage,value,sources:(value,[])):
            self.start();Worker(self.service).once()
        self.assertEqual(self.job()['status'],'blocked')
        self.start();Worker(self.service).once()
        self.assertEqual(self.run_value().wait_reason,'final_confirmation')
        self.assertEqual(len(self.model.calls),8)
        self.assertEqual(self.run_value().node_runs[-1]['citation_repairs'][0]['reason'],'quote_outer_whitespace')

    def test_review_attempt_limit_keeps_draft_for_human_without_error_or_approval(self):
        self.start();Worker(self.service).once()
        for i in range(3):
            content=dict(self.run_value().drafts[-1]['content']);content['body']='用户改稿'+str(i)
            self.action('edit',content)
            self.start();Worker(self.service).once()
        run=self.run_value()
        self.assertEqual(run.run_status,'WAITING_USER')
        self.assertEqual(run.wait_reason,'revision_limit')
        self.assertIsNone(run.review)
        self.assertIsNone(run.accepted_ref)
        self.assertEqual(len(self.model.calls),10)
        self.assertEqual(self.job()['status'],'waiting')
        self.assertFalse(self.job().get('error'))
        self.assertEqual(run.drafts[-1]['content']['body'],'用户改稿2')

    def test_invalid_review_can_be_recovered_free_then_edited_reaudited_and_confirmed(self):
        self.invalid_citation_review()
        before=self.service.view(self.run_value())
        self.assertIn('repair_review',before['allowed_actions'])
        self.assertEqual(len(before['review_recovery']['invalid_quotes']),1)
        with self.assertRaises(DomainError):self.step()
        self.assertEqual(len(self.model.calls),8)
        command=dict(action='repair_review',payload={},version=self.run_value().status_version,key=str(uuid4()))
        repaired=self.service.action(self.owner,self.run_id,command)
        replay=self.service.action(self.owner,self.run_id,command)
        self.assertEqual(replay['status_version'],repaired['status_version'])
        self.assertEqual(repaired['review']['decision'],'revision_required')
        self.assertIn('edit',repaired['allowed_actions']);self.assertNotIn('accept',repaired['allowed_actions'])
        self.assertEqual(repaired['usage'],before['usage'])
        self.assertEqual(repaired['calls'],before['calls'])
        self.assertEqual(len(repaired['review']['claim_map']),1)
        self.assertEqual(repaired['background']['status'],'paused');self.assertIsNone(repaired['background']['error'])
        with self.assertRaises(DomainError):self.action('accept',dict(draft_ref=repaired['drafts'][-1]['ref'],review_ref=repaired['review']['ref']))
        changed=dict(repaired['drafts'][-1]['content']);changed['body']='我按照课程建立资料文件夹。'
        edited=self.action('edit',changed)
        self.assertEqual(edited['current_stage'],'reviewer')
        self.step();Worker(self.service).once()
        ready=self.service.view(self.run_value())
        self.assertEqual(len(self.model.calls),9)
        self.assertIn('accept',ready['allowed_actions'])
        accepted=self.action('accept',dict(draft_ref=ready['drafts'][-1]['ref'],review_ref=ready['review']['ref']))
        self.assertEqual(accepted['run_status'],'SUCCEEDED')

    def test_review_recovery_rejects_stale_owner_active_and_nonquote_errors(self):
        self.invalid_citation_review()
        command=dict(action='repair_review',payload={},version=self.run_value().status_version,key=str(uuid4()))
        with self.assertRaises(DomainError):self.service.action('other-owner',self.run_id,command)
        with self.assertRaises(DomainError):self.service.action(self.owner,self.run_id,{**command,'version':0})
        with self.store.connect() as db:db.execute("UPDATE runtime_jobs SET status='running' WHERE run_id=?",(self.run_id,))
        with self.assertRaises(DomainError):self.service.action(self.owner,self.run_id,command)
        with self.store.connect() as db:
            db.execute("UPDATE runtime_jobs SET status='blocked' WHERE run_id=?",(self.run_id,))
            call_id,raw=db.execute("SELECT id,response_json FROM live_calls WHERE run_id=? AND stage='review'",(self.run_id,)).fetchone()
            value=json.loads(raw);value['checks']=[]
            db.execute('UPDATE live_calls SET response_json=? WHERE id=?',(json.dumps(value),call_id))
        self.assertFalse(self.service.view(self.run_value())['review_recovery']['available'])
        with self.assertRaises(DomainError):self.service.action(self.owner,self.run_id,command)
        self.assertEqual(len(self.model.calls),8)

    def historical_extra_review(self):
        self.invalid_citation_review()
        self.action('repair_review',{})
        historical=self.run_value().review['issues'][0]['issue_id']
        base=self.model.complete
        def reviews(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='review':
                value.update(decision='revision_required',next_action='revise',issues=[{
                    'issue_id':'current','severity':'major','state':'open','location':'body',
                    'excerpt':'完整正文','reason':'缺少依据','suggestion':'补充原始资料'}])
                if self.model.calls.count('review')==3:
                    value['previous_issue_results']=[{'issue_id':'current','result':'unresolved'},
                                                     {'issue_id':historical,'result':'unresolved'}]
            return value,tokens
        self.model.complete=reviews
        for _ in range(4):self.step();Worker(self.service).once()
        self.assertEqual(self.run_value().iteration,2)
        self.assertEqual(self.job()['status'],'blocked')
        return historical

    def test_historical_extra_ids_recover_without_changing_unresolved_or_restarting_calls(self):
        historical=self.historical_extra_review()
        before=self.service.view(self.run_value());calls=list(self.model.calls)
        self.assertTrue(before['review_recovery']['available'])
        self.assertEqual(before['review_recovery']['excluded_previous_results'],[{'issue_id':historical,'result':'unresolved'}])
        repaired=self.action('repair_review',{})
        self.assertEqual(repaired['review']['previous_issue_results'],[{'issue_id':'current','result':'unresolved'}])
        self.assertEqual(repaired['review']['decision'],'revision_required')
        self.assertEqual(repaired['wait_reason'],'revision_limit')
        self.assertNotIn('accept',repaired['allowed_actions'])
        self.assertEqual(repaired['usage'],before['usage']);self.assertEqual(self.model.calls,calls)
        self.assertEqual(repaired['node_runs'][-1]['input']['excluded_previous_results'][0]['issue_id'],historical)

    def test_historical_recovery_rejects_missing_duplicate_unknown_and_approval(self):
        historical=self.historical_extra_review()
        with self.store.connect() as db:
            call_id,raw=db.execute(f"SELECT id,response_json FROM live_calls WHERE run_id=? AND stage='review' ORDER BY {self.store.order_column} DESC LIMIT 1",(self.run_id,)).fetchone()
        original=json.loads(raw)
        variants=[[],[{'issue_id':'current','result':'unresolved'}]*2,
            [{'issue_id':'current','result':'unresolved'},{'issue_id':'unknown','result':'unresolved'}]]
        for results in variants:
            value=dict(original,previous_issue_results=results)
            with self.store.connect() as db:db.execute('UPDATE live_calls SET response_json=? WHERE id=?',(json.dumps(value),call_id))
            self.assertFalse(self.service.view(self.run_value())['review_recovery']['available'])
        value=dict(original,decision='approved',next_action='await_user_confirmation')
        with self.store.connect() as db:db.execute('UPDATE live_calls SET response_json=? WHERE id=?',(json.dumps(value),call_id))
        self.assertFalse(self.service.view(self.run_value())['review_recovery']['available'])

    def test_step_pauses_after_each_business_stage_and_survives_restart(self):
        for expected_calls in (2,3,4,5,6,7,8):
            self.step()
            Worker(Service(Store(self.store.path),self.config,self.model)).once()
            self.assertEqual(len(self.model.calls),expected_calls,self.job())
            self.assertEqual(self.job()['status'],'waiting' if expected_calls==8 else 'paused')
            self.assertIsNone(self.job()['error'])
        self.assertEqual(self.run_value().wait_reason,'final_confirmation')

    def test_step_command_is_idempotent_and_cannot_replace_active_job(self):
        command=dict(action='step',version=self.run_value().status_version,key=str(uuid4()))
        self.service.background(self.owner,self.run_id,command)
        self.service.background(self.owner,self.run_id,command)
        with self.assertRaises(DomainError) as rejected:self.step()
        self.assertEqual(rejected.exception.code,'JOB_ACTIVE')
        Worker(self.service).once()
        self.service.background(self.owner,self.run_id,command)
        self.assertEqual(self.job()['status'],'paused')
        self.assertEqual(len(self.model.calls),2)
        with self.assertRaises(DomainError):self.step('retry_research',queries=['改词'])
        self.start();Worker(self.service).once()
        self.assertEqual(self.job()['status'],'waiting')
        self.assertEqual(len(self.model.calls),8)

    def test_step_replay_does_not_advance_past_requested_stage(self):
        self.step();Worker(self.service).once()
        self.step()
        def crash(point,stage):
            if point=='after_commit' and stage=='strategy':raise RuntimeError('crash before checkpoint')
        Worker(self.service,fault=crash).once()
        self.assertEqual(self.job()['status'],'blocked')
        # Reclaimed worker continues the original command after a process crash.
        with self.store.connect() as db:
            db.execute("UPDATE runtime_jobs SET status='queued' WHERE run_id=?",(self.run_id,))
        Worker(self.service).once()
        self.assertEqual(self.model.calls.count('strategy'),1)
        self.assertEqual(len(self.model.calls),3)
        self.assertEqual(self.job()['status'],'paused')

    def test_research_retry_keeps_report_and_stops_before_model(self):
        from unittest.mock import patch
        self.action('cancel',{})
        self.run_id=self.service.create(self.owner,dict(topic='公开护肤资料',audience='读者',tone='朴实',material='',allow_hypothesis=True,mode='live',web_research={'enabled':True,'queries':['护肤顺序']}))['run_id']
        failed={'status':'insufficient','searches':[],'reads':[],'sources':[]}
        with patch('backend.web_research.collect',return_value=failed):
            self.step();Worker(self.service).once()
        self.assertEqual(self.job()['status'],'blocked')
        old_snapshot=self.run_value().snapshot_id
        self.step('retry_research',queries=['洁面 保湿'])
        success={'status':'complete','searches':[],'reads':[],'sources':[{'source_id':'test-source','text':'公开护肤资料原文：洁面后按产品说明保湿。'}]}
        with patch('backend.web_research.collect',return_value=success):Worker(self.service).once()
        run=self.run_value()
        self.assertEqual(self.job()['status'],'paused',self.job())
        self.assertEqual(self.model.calls,[])
        self.assertEqual(run.context['web_research_history'][0]['status'],'insufficient')
        self.assertNotEqual(run.snapshot_id,old_snapshot)
        self.assertEqual(run.context['web_research']['queries'],['洁面 保湿'])
        with self.assertRaises(DomainError):self.step('retry_research',queries=['其他主题'])

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
        fixture=json.loads((Path(__file__).parent/'public_materials.json').read_text())['sources'][0]
        account=self.service.operations.read(self.owner)['accounts'][0]['id']
        from test_original_creation_http import RoutingVectors
        self.service.knowledge.embedding_provider=RoutingVectors()
        self.service.knowledge.save(self.owner,dict(account_id=account,title=fixture['title'],text=fixture['text'],classification=dict(domains=['apparel'],channel='any',format='any',material_type='fact')),source_type='editorial_summary',source_url=fixture['url'],metadata=fixture)
        data=dict(creation=dict(domains=['apparel'],channel='xiaohongshu',format='note'),topic='胶囊衣橱',audience='虚构读者',tone='清楚',material='',mode='live',allow_hypothesis=True,
                  operations=dict(account_id=account,platform='xiaohongshu',account='虚构账号'),knowledge={'enabled':True})
        self.run_id=self.service.create(self.owner,data)['run_id']
        self.start();Worker(self.service).once()
        self.assertEqual(self.run_value().wait_reason,'final_confirmation',self.job())
        for node in self.run_value().node_runs:
            self.assertTrue(node['input']['materials'][0]['source_id'].startswith('kb:'))
            self.assertEqual(node['input']['creation_classification']['domains'],['apparel'])
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
                        deadline=time.monotonic()+20
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
                clean={**env,'FIXTURE_POINT':'none'}
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

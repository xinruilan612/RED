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

    def test_parse_failure_keeps_usage_and_explicit_resume_reuses_successful_branch(self):
        from backend.provider import ProviderOutputError
        base=self.model.complete
        failed=[]
        def complete_result(messages):
            if '负责 audience 的' in messages[0]['content'] and not failed:
                failed.append(True)
                raise ProviderOutputError('模型正文格式无效',tokens=210,
                    metadata={'request_id':'fixture-response','input_tokens':100,'output_tokens':110})
            value,tokens=base(messages)
            return value,tokens,{}
        self.model.complete_result=complete_result
        self.start();Worker(self.service).once()
        self.assertEqual(self.job()['status'],'blocked')
        report=self.service.view(self.run_value())
        self.assertEqual(report['usage']['unknown_calls'],0)
        self.assertEqual(self.model.calls.count('research'),1)
        with self.store.connect() as db:
            actual=db.execute("SELECT actual FROM live_calls WHERE run_id=? AND state='failed'",(self.run_id,)).fetchone()[0]
            audit=db.execute("SELECT request_id,input_tokens,output_tokens FROM model_audit WHERE run_id=? AND outcome='failed'",(self.run_id,)).fetchone()
        self.assertEqual(actual,210);self.assertEqual(tuple(audit),('fixture-response',100,110))
        self.assertFalse(Worker(self.service).once())  # No implicit paid retry.
        self.service=Service(self.store,self.config,self.model)
        self.start();Worker(self.service).once()
        self.assertEqual(self.run_value().run_status,'WAITING_USER')
        self.assertEqual(self.model.calls.count('research'),1)
        self.assertEqual(self.model.calls.count('audience'),1)
        self.assertEqual(self.service.view(self.run_value())['usage']['unknown_calls'],0)

    def test_parse_failure_unknown_usage_blocks_resume_before_queue(self):
        from backend.provider import ProviderOutputError
        def failure(messages):raise ProviderOutputError('无法确认用量')
        self.model.complete_result=failure
        self.start();Worker(self.service).once()
        self.assertEqual(self.job()['status'],'blocked')
        with self.assertRaises(DomainError) as caught:self.start()
        self.assertEqual(caught.exception.code,'USAGE_UNKNOWN')
        report=self.service.view(self.run_value())
        self.assertNotIn('next',report['allowed_actions'])
        self.assertNotIn('recover',report['allowed_actions'])
        self.assertGreater(report['usage']['unknown_calls'],0)
        self.assertFalse(Worker(self.service).once())

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
        for i in range(2):
            content=dict(self.run_value().drafts[-1]['content']);content['body']='用户改稿'+str(i)
            self.action('edit',content)
            self.start();Worker(self.service).once()
        content=dict(self.run_value().drafts[-1]['content']);content['body']='用户改稿2'
        self.action('edit',content)
        version=self.run_value().status_version
        with self.assertRaises(DomainError) as error:self.start()
        self.assertEqual(error.exception.code,'STAGE_ATTEMPT_LIMIT')
        run=self.run_value()
        self.assertEqual(run.status_version,version)
        self.assertEqual(run.run_status,'RUNNING')
        self.assertTrue(self.service.view(run)['review_execution']['blocked'])
        self.assertIsNone(run.review)
        self.assertIsNone(run.accepted_ref)
        self.assertEqual(len(self.model.calls),10)
        self.assertEqual(self.job()['status'],'waiting')
        self.assertFalse(self.job().get('error'))
        self.assertEqual(run.drafts[-1]['content']['body'],'用户改稿2')

    def test_valid_revision_limit_preserves_manual_edit_and_model_call_caps(self):
        base=self.model.complete
        def revision(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='revise':value['body']='完整正文 · 改稿'+str(self.model.calls.count('revise'))
            if self.model.calls[-1]=='review':
                value.update(decision='revision_required',next_action='revise',issues=[{
                    'issue_id':'still-open','severity':'major','state':'open','location':'body',
                    'excerpt':'完整正文','reason':'尚未解决的真实问题','suggestion':'请核对材料并修改'}])
                for item in value['previous_issue_results']:item['result']='unresolved'
            return value,tokens
        self.model.complete=revision;self.start();Worker(self.service).once()
        run=self.run_value();view=self.service.view(run)
        self.assertEqual(run.run_status,'WAITING_USER')
        self.assertEqual(run.wait_reason,'revision_limit')
        self.assertEqual(len(run.drafts),3)
        self.assertIsNone(run.accepted_ref)
        before_calls=len(self.model.calls)
        self.assertEqual(before_calls,12)
        self.assertEqual(len(run.reviews),3)
        self.assertEqual(self.model.calls.count('review'),3)
        self.assertEqual(self.job()['status'],'waiting')
        self.assertIn('edit',view['allowed_actions']);self.assertNotIn('accept',view['allowed_actions'])
        changed=dict(run.drafts[-1]['content']);changed['body']='人工核对后保留的新稿。'
        self.action('edit',changed)
        self.assertEqual(len(self.model.calls),before_calls)
        with self.assertRaises(DomainError) as error:self.start()
        self.assertEqual(error.exception.code,'STAGE_ATTEMPT_LIMIT')
        self.assertEqual(len(self.model.calls),before_calls)
        self.assertLessEqual(self.model.calls.count('review'),3)
        current=self.service.view(self.run_value())
        self.assertTrue(current['review_execution']['blocked'])
        self.assertNotIn('next',current['allowed_actions'])
        self.assertIn('adopt_manual',current['allowed_actions'])

    def test_exhausted_reviews_block_paid_revision_before_a_fourth_review_would_be_needed(self):
        base=self.model.complete
        def later_revision(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='review' and self.model.calls.count('review')>1:
                value.update(decision='revision_required',next_action='revise',issues=[{
                    'issue_id':'still-open','severity':'major','state':'open','location':'body',
                    'excerpt':'完整正文','reason':'尚未解决的问题','suggestion':'核对来源后修改'}])
                for item in value['previous_issue_results']:item['result']='unresolved'
            return value,tokens
        self.model.complete=later_revision
        self.start();Worker(self.service).once()
        self.assertEqual(self.run_value().wait_reason,'final_confirmation')
        content=dict(self.run_value().drafts[-1]['content']);content['body']='完整正文 · 人工修改'
        self.action('edit',content)
        for _ in range(3):self.step();Worker(self.service).once()
        run=self.run_value();view=self.service.view(run)
        self.assertEqual(self.model.calls.count('review'),3)
        self.assertEqual((run.run_status,run.current_stage,run.iteration),('RUNNING','content',2))
        self.assertEqual(view['review_execution']['used'],3)
        self.assertTrue(view['review_execution']['blocked']);self.assertFalse(view['review_execution']['replayable'])
        self.assertNotIn('next',view['allowed_actions']);self.assertIn('adopt_manual',view['allowed_actions'])
        before_calls=len(self.model.calls);before_version=run.status_version
        for execute in (self.start,self.step):
            with self.assertRaises(DomainError) as error:execute()
            self.assertEqual(error.exception.code,'STAGE_ATTEMPT_LIMIT')
        self.assertEqual(len(self.model.calls),before_calls)
        self.assertEqual(self.run_value().status_version,before_version)

    def test_automatic_job_does_not_charge_a_revision_after_third_review(self):
        base=self.model.complete
        def later_revision(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='review' and self.model.calls.count('review')>1:
                value.update(decision='revision_required',next_action='revise',issues=[{
                    'issue_id':'still-open','severity':'major','state':'open','location':'body',
                    'excerpt':'完整正文','reason':'尚未解决的问题','suggestion':'核对来源后修改'}])
                for item in value['previous_issue_results']:item['result']='unresolved'
            return value,tokens
        self.model.complete=later_revision
        self.start();Worker(self.service).once()
        content=dict(self.run_value().drafts[-1]['content']);content['body']='完整正文 · 人工修改'
        self.action('edit',content);self.start();Worker(self.service).once()
        run=self.run_value()
        self.assertEqual((run.run_status,run.wait_reason),('WAITING_USER','revision_limit'))
        self.assertEqual(self.model.calls.count('review'),3)
        self.assertEqual(self.model.calls.count('revise'),1)
        self.assertEqual(len(self.model.calls),11)
        self.assertIsNone(run.accepted_ref)
        view=self.service.view(run)
        self.assertIn('edit',view['allowed_actions']);self.assertIn('adopt_manual',view['allowed_actions'])
        self.assertNotIn('next',view['allowed_actions'])

    def test_inconsistent_revision_with_questions_recovers_only_to_human_not_approval(self):
        base=self.model.complete
        def inconsistent(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='review':
                value.update(decision='revision_required',next_action='revise',issues=[],human_questions=['请确认仅作为未实测的样例使用。'])
            return value,tokens
        self.model.complete=inconsistent;self.start();Worker(self.service).once()
        before=self.service.view(self.run_value())
        self.assertEqual(self.job()['status'],'blocked')
        self.assertTrue(before['review_recovery']['available'])
        recovered=self.action('repair_review',{})
        self.assertEqual(recovered['review']['decision'],'needs_human')
        self.assertEqual(recovered['wait_reason'],'missing_material')
        self.assertNotIn('accept',recovered['allowed_actions'])
        self.assertEqual(recovered['usage'],before['usage'])
        self.assertEqual(recovered['calls'],before['calls'])
        self.assertEqual(recovered['review']['human_questions'],['请确认仅作为未实测的样例使用。'])
        self.assertEqual(len(self.model.calls),8)

    def test_empty_revision_without_human_questions_stays_blocked(self):
        base=self.model.complete
        def empty(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='review':value.update(decision='revision_required',next_action='revise',issues=[],human_questions=[])
            return value,tokens
        self.model.complete=empty;self.start();Worker(self.service).once()
        self.assertFalse(self.service.view(self.run_value())['review_recovery']['available'])
        with self.assertRaises(DomainError):self.action('repair_review',{})
        self.assertEqual(len(self.model.calls),8)

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

    def invalid_draft_excerpt_review(self):
        base=self.model.complete
        def invalid(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='review' and self.model.calls.count('review')==1:
                value['claim_map']=[{'excerpt':'这是一份公开资料的测试摘要。','source_id':'user-material','quote':'这是一份公开资料的测试摘要。'},
                    {'excerpt':'完整正文','source_id':'user-material','quote':'公开资料'}]
            return value,tokens
        self.model.complete=invalid
        self.start();Worker(self.service).once()
        self.assertEqual(self.job()['status'],'blocked')
        return self.service.view(self.run_value())

    def test_unlocated_review_quote_recovers_without_guessing_approval_or_billing(self):
        before=self.invalid_draft_excerpt_review()
        self.assertTrue(before['review_recovery']['available'])
        with self.store.connect() as db:
            row=db.execute("SELECT id,response_json,actual,state FROM live_calls WHERE run_id=? AND stage='review'",(self.run_id,)).fetchone()
        repaired=self.action('repair_review',{})
        self.assertEqual(repaired['usage'],before['usage'])
        self.assertEqual(repaired['calls'],before['calls'])
        self.assertEqual(repaired['drafts'],before['drafts'])
        self.assertEqual(repaired['review']['decision'],'revision_required')
        self.assertNotIn('accept',repaired['allowed_actions'])
        self.assertEqual(repaired['review']['claim_map'],[{'excerpt':'完整正文','source_id':'user-material','quote':'公开资料'}])
        issue=repaired['review']['issues'][-1]
        self.assertEqual(issue['excerpt'],before['drafts'][-1]['content']['body'])
        self.assertEqual(next(c for c in repaired['review']['checks'] if c['name']=='evidence_integrity')['result'],'fail')
        self.assertEqual(repaired['node_runs'][-1]['input']['excluded_claim_map'][0]['excerpt'],'这是一份公开资料的测试摘要。')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT id,response_json,actual,state FROM live_calls WHERE id=?',(row[0],)).fetchone(),row)
        self.start();Worker(self.service).once()
        ready=self.service.view(self.run_value())
        self.assertEqual(ready['review']['decision'],'approved')
        self.assertEqual(self.model.calls[-2:],['revise','review'])
        self.assertEqual(len(self.model.calls),10)
        accepted=self.action('accept',dict(draft_ref=ready['drafts'][-1]['ref'],review_ref=ready['review']['ref']))
        self.assertEqual(accepted['run_status'],'SUCCEEDED')

    def test_unlocated_review_recovery_rejects_unknown_usage_old_draft_and_snapshot(self):
        self.invalid_draft_excerpt_review()
        with self.store.connect() as db:
            row=db.execute("SELECT id,actual FROM live_calls WHERE run_id=? AND stage='review'",(self.run_id,)).fetchone()
            db.execute('UPDATE live_calls SET actual=NULL WHERE id=?',(row[0],))
        self.assertFalse(self.service.view(self.run_value())['review_recovery']['available'])
        with self.store.connect() as db:
            db.execute('UPDATE live_calls SET actual=? WHERE id=?',(row[1],row[0]))
            db.execute("UPDATE model_audit SET snapshot_id='stale' WHERE call_id=?",(row[0],))
        self.assertFalse(self.service.view(self.run_value())['review_recovery']['available'])
        with self.store.connect() as db:
            db.execute('UPDATE model_audit SET snapshot_id=?,started=0 WHERE call_id=?',(self.run_value().snapshot_id,row[0]))
        self.assertFalse(self.service.view(self.run_value())['review_recovery']['available'])
        self.assertEqual(len(self.model.calls),8)

    def test_unlocated_review_recovery_is_owner_version_guarded_and_idempotent(self):
        self.invalid_draft_excerpt_review()
        command=dict(action='repair_review',payload={},version=self.run_value().status_version,key=str(uuid4()))
        with self.assertRaises(DomainError):self.service.action('other-owner',self.run_id,command)
        with self.assertRaises(DomainError):self.service.action(self.owner,self.run_id,{**command,'version':0})
        with self.store.connect() as db:db.execute("UPDATE runtime_jobs SET status='running' WHERE run_id=?",(self.run_id,))
        with self.assertRaises(DomainError):self.service.action(self.owner,self.run_id,command)
        with self.store.connect() as db:db.execute("UPDATE runtime_jobs SET status='blocked' WHERE run_id=?",(self.run_id,))
        repaired=self.service.action(self.owner,self.run_id,command)
        replay=self.service.action(self.owner,self.run_id,command)
        self.assertEqual(replay['status_version'],repaired['status_version'])
        self.assertEqual(len(self.model.calls),8)

    def test_unlocated_review_recovery_cannot_hide_other_schema_failures(self):
        self.invalid_draft_excerpt_review()
        with self.store.connect() as db:
            call_id,raw=db.execute("SELECT id,response_json FROM live_calls WHERE run_id=? AND stage='review'",(self.run_id,)).fetchone()
            value=json.loads(raw);value['checks']=[]
            db.execute('UPDATE live_calls SET response_json=? WHERE id=?',(json.dumps(value),call_id))
        self.assertFalse(self.service.view(self.run_value())['review_recovery']['available'])
        with self.assertRaises(DomainError):self.action('repair_review',{})
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

    def test_compound_review_recovery_command_is_free_idempotent_and_allows_edit(self):
        historical=self.historical_extra_review()
        # The third response has both an obsolete issue ID and invalid citation.
        with self.store.connect() as db:
            call_id,raw=db.execute(f"SELECT id,response_json FROM live_calls WHERE run_id=? AND stage='review' ORDER BY {self.store.order_column} DESC LIMIT 1",(self.run_id,)).fetchone()
            value=json.loads(raw)
            value['claim_map']=[{'excerpt':'完整正文','source_id':'user-material','quote':'不存在的资料引用'}]
            db.execute('UPDATE live_calls SET response_json=? WHERE id=?',(json.dumps(value),call_id))
            original=db.execute('SELECT response_json,actual,state FROM live_calls WHERE id=?',(call_id,)).fetchone()
        before=self.service.view(self.run_value());calls=list(self.model.calls)
        self.assertTrue(before['review_recovery']['available'])
        command=dict(action='repair_review',payload={},version=self.run_value().status_version,key=str(uuid4()))
        repaired=self.service.action(self.owner,self.run_id,command)
        replay=self.service.action(self.owner,self.run_id,command)
        self.assertEqual(repaired['status_version'],replay['status_version'])
        self.assertEqual(repaired['review'],replay['review'])
        self.assertEqual(repaired['usage'],before['usage'])
        self.assertEqual(repaired['calls'],before['calls'])
        self.assertEqual(self.model.calls,calls)
        self.assertEqual(repaired['node_runs'][-1]['model_calls'],0)
        self.assertEqual(repaired['node_runs'][-1]['input']['excluded_previous_results'],[{'issue_id':historical,'result':'unresolved'}])
        self.assertEqual(len(repaired['node_runs'][-1]['input']['excluded_claim_map']),1)
        self.assertEqual(repaired['review']['previous_issue_results'],[{'issue_id':'current','result':'unresolved'}])
        self.assertNotIn('accept',repaired['allowed_actions'])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT response_json,actual,state FROM live_calls WHERE id=?',(call_id,)).fetchone(),original)
        changed=dict(repaired['drafts'][-1]['content']);changed['body']='核对后修改的正文，仍须重新审核。'
        edited=self.action('edit',changed)
        self.assertEqual(edited['current_stage'],'reviewer')
        self.assertIsNone(edited['review'])
        self.assertEqual(edited['drafts'][-1]['content']['body'],changed['body'])
        self.assertNotEqual(edited['drafts'][-1]['ref'],repaired['drafts'][-1]['ref'])
        self.assertEqual(edited['prior_review']['ref'],repaired['review']['ref'])
        self.assertNotIn('accept',edited['allowed_actions'])
        with self.assertRaises(DomainError) as caught:self.start()
        self.assertEqual(caught.exception.code,'STAGE_ATTEMPT_LIMIT')
        self.assertEqual(self.model.calls,calls)  # Third-review cap still applies.

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
        success={'status':'complete','searches':[],'reads':[],'sources':[{'source_id':'test-source','text':'公开原文'}]}
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
        with self.assertRaises(DomainError) as caught:self.start()
        self.assertEqual(caught.exception.code,'USAGE_UNKNOWN')
        self.assertFalse(Worker(self.service).once())
        self.assertEqual(len(self.model.calls),before)
        self.assertEqual(self.job()['status'],'blocked')

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

    def test_delete_wins_late_results_and_preserves_usage(self):
        self.start();deleted=[]
        def delete(point,stage):
            if point=='after_response' and stage=='strategy' and not deleted:
                deleted.append(True)
                self.store.set_visibility(self.run_id,self.owner,True)
        Worker(self.service,fault=delete).once()
        self.assertTrue(deleted)
        self.assertEqual(self.run_value().run_status,'CANCELLED')
        self.assertFalse(self.run_value().artifacts)
        self.assertEqual(self.job()['status'],'done')
        self.assertEqual(self.store.list_runs(self.owner),[])
        self.assertEqual(self.store.list_runs(self.owner,deleted=True)[0].run_id,self.run_id)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT state FROM live_calls WHERE stage='strategy'").fetchone()[0],'validated')
        self.store.set_visibility(self.run_id,self.owner,False)
        self.assertEqual(self.run_value().run_status,'CANCELLED')

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
                     'FIXTURE_RUN_ID':self.run_id,'FIXTURE_OWNER':self.owner,
                     'FIXTURE_STAGE':'strategy','FIXTURE_MARKER':str(marker),
                     'PYTHONDONTWRITEBYTECODE':'1','PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'}
                with tempfile.TemporaryFile() as output:
                    process=subprocess.Popen([sys.executable,str(root/'tests/runtime_process_fixture.py')],env=env,stdout=output,stderr=output)
                    try:
                        deadline=time.monotonic()+20
                        while not marker.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.05)
                        if not marker.exists():
                            output.seek(0);self.fail('worker did not reach crash point: '+output.read().decode('utf-8'))
                        with self.store.connect() as db:
                            killed=db.execute('SELECT id,token,generation FROM runtime_jobs WHERE run_id=?',(self.run_id,)).fetchone()
                        self.assertIsNotNone(killed[1])
                        process.kill();process.wait(timeout=5)
                        self.assertNotEqual(process.returncode,0)
                    finally:
                        if process.poll() is None:process.kill();process.wait()
                # A real killed process cannot renew its lease. Before expiry,
                # another worker must not claim it; then simulate elapsed time
                # only for that exact killed job, without changing its fencing token.
                self.assertIsNone(self.service.jobs.claim())
                with self.store.connect() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM live_calls WHERE run_id=?',(self.run_id,)).fetchone()[0],3)
                    changed=db.execute("UPDATE runtime_jobs SET lease_until=? WHERE id=? AND run_id=? AND token=? AND generation=? AND status='running'",
                                       (time.time()-1,killed[0],self.run_id,killed[1],killed[2])).rowcount
                    self.assertEqual(changed,1)
                clean={**env,'FIXTURE_POINT':'none'}
                result=subprocess.run([sys.executable,str(root/'tests/runtime_process_fixture.py')],env=clean,capture_output=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stderr.decode('utf-8'))
                self.assertEqual(self.run_value().wait_reason,'final_confirmation',self.job())
                with self.store.connect() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM live_calls WHERE run_id=?',(self.run_id,)).fetchone()[0],8)
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM runtime_nodes WHERE run_id=?',(self.run_id,)).fetchone()[0],8)
                    self.assertEqual(db.execute('SELECT generation FROM runtime_jobs WHERE id=?',(killed[0],)).fetchone()[0],killed[2]+1)


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

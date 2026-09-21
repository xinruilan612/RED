"""Offline fixtures verify wiring/guards; these are NOT real DeepSeek quality evidence."""
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from urllib.error import HTTPError

from backend.contracts import DomainError
from backend.provider import Config, DeepSeek, load_config, decode_response, NoRedirect
from backend.execution import Executor
from backend.live import schema, normalize, material_records, messages_for
from backend.demo import validate_brief
from backend.store import Store
from backend.web import view


class FixtureModel:
    def __init__(self):self.calls=[]
    def complete(self,messages):
        stage=re.search(r'负责 (\w+) 的',messages[0]['content']).group(1)
        self.calls.append(stage)
        value=schema(stage)
        if stage=='research':value['facts']=[]
        if stage=='body':value['selected_title']='候选一'
        if stage=='review':
            old=json.loads(messages[1]['content']).get('previous_review')
            value['previous_issue_results']=[{'issue_id':i['issue_id'],'result':'resolved'} for i in old['issues']] if old else []
            value['checks'][-2]['result']='unknown'
        return value,120


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'test.sqlite')
        self.config=Config('test-secret-do-not-leak');self.model=FixtureModel()
        self.executor=Executor(self.store,self.config,self.model)
        context=validate_brief({'topic':'资料整理','audience':'学生','tone':'清楚','material':'我用文件夹整理课程笔记。'})
        context['mode']='live';self.run=self.store.create('me','snapshot',context)
    def tearDown(self):self.temp.cleanup()
    def step(self,run=None,key=None):
        r=run or self.run
        self.run=self.executor.step(r.run_id,'me',r.status_version,key or str(uuid4()));return self.run
    def until_review(self):
        for _ in range(7):self.step()
        self.assertEqual(self.run.wait_reason,'final_confirmation')
        return self.run

    def test_quick_workflow_uses_one_generation_and_one_independent_review(self):
        self.run.context['workflow']='quick'
        from dataclasses import asdict
        with self.store.connect() as db:
            db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(asdict(self.run)),self.run.run_id))
        self.step()
        self.assertEqual(self.model.calls,['quick'])
        self.assertEqual(self.run.current_stage,'reviewer')
        self.assertEqual([a['stage'] for a in self.run.artifacts],['quick'])
        self.assertEqual(self.run.branches,{})
        self.assertEqual(len(self.run.drafts),1)
        _,inputs=messages_for(self.run,'review')
        self.assertEqual(inputs['branches'],{})
        self.assertEqual(inputs['draft'],self.run.drafts[-1]['content'])
        self.step()
        self.assertEqual(self.model.calls,['quick','review'])
        self.assertEqual(self.run.wait_reason,'final_confirmation')
        self.assertEqual(self.executor.public(self.run)['usage']['model_calls'],2)
        self.assertEqual(self.executor.public(self.run)['usage']['tokens'],240)

    def test_eight_calls_text_flow_edit_reaudit_accept_and_no_secrets(self):
        run=self.until_review();self.assertEqual(len(self.model.calls),8)
        self.assertEqual({n['agent'] for n in run.node_runs},{'audience','research','content','reviewer'})
        self.assertEqual(len(run.artifacts),5)
        old=run.drafts[0]
        changed=dict(old['content']);changed['body']='我把课程资料放在对应文件夹里。'
        self.run=self.store.command(run.run_id,'me',run.status_version,'edit','edit',{'content':changed})
        self.assertEqual(self.run.drafts[0],old);self.assertIsNone(self.run.review)
        self.step();run=self.run
        run=self.store.command(run.run_id,'me',run.status_version,'accept','accept',{'draft_ref':run.drafts[-1]['ref'],'review_ref':run.review['ref']})
        self.assertEqual(run.run_status,'SUCCEEDED')
        result=view(run,self.executor)
        self.assertEqual(result['usage']['model_calls'],9)
        self.assertEqual(result['usage']['tokens'],1080)
        self.assertNotIn(self.config.api_key,json.dumps(result));self.assertNotIn(self.config.api_key,repr(self.config))

    def test_model_revision_preserves_issues_and_reaudits(self):
        base=self.model.complete
        def revise_once(messages):
            value,tokens=base(messages)
            stage=self.model.calls[-1]
            if stage=='review' and self.model.calls.count('review')==1:
                value.update(decision='revision_required',next_action='revise',issues=[{
                    'issue_id':'i1','severity':'major','state':'open','location':'body',
                    'excerpt':'完整正文','reason':'信息不足','suggestion':'补充具体步骤'}])
            return value,tokens
        self.model.complete=revise_once
        for _ in range(7):self.step()
        self.assertEqual(self.run.review['decision'],'revision_required')
        self.step();self.assertEqual(len(self.run.drafts),2)
        self.step();self.assertEqual(self.run.wait_reason,'final_confirmation')
        self.assertEqual(self.run.review['previous_issue_results'],[{'issue_id':'i1','result':'resolved'}])

    def test_revision_context_keeps_evidence_and_issues_without_repeating_upstream(self):
        base=self.model.complete
        def revise_once(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='review':
                value.update(decision='revision_required',next_action='revise',issues=[{
                    'issue_id':'i1','severity':'major','state':'open','location':'body',
                    'excerpt':'完整正文','reason':'信息不足','suggestion':'补充具体步骤'}])
            return value,tokens
        self.model.complete=revise_once
        for _ in range(7):self.step()
        _,data=messages_for(self.run,'revise')
        self.assertNotIn('upstream',data)
        self.assertEqual(set(data['branches']),{'audience','research'})
        self.assertEqual(data['previous_review']['issues'][0]['issue_id'],'i1')
        self.assertNotIn('checks',data['previous_review'])
        self.assertEqual(data['draft'],self.run.drafts[-1]['content'])
        self.assertEqual(data['materials'],material_records(self.run.context))

    def test_three_rejected_outputs_fail_without_fourth_generation(self):
        base=self.model.complete
        def reject(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='review':
                value.update(decision='revision_required',next_action='revise',issues=[{
                    'issue_id':'same','severity':'major','state':'open','location':'body',
                    'excerpt':'正文','reason':'仍不满足需求','suggestion':'增加具体内容'}])
                value['previous_issue_results']=[{'issue_id':'same','result':'unresolved'}] if self.model.calls.count('review')>1 else []
            return value,tokens
        self.model.complete=reject
        for _ in range(11):self.step()
        self.assertEqual(self.run.run_status,'FAILED')
        self.assertEqual(self.model.calls.count('body')+self.model.calls.count('revise'),3)
        self.assertEqual(self.model.calls.count('review'),3)
        self.assertEqual(len(self.run.drafts),3)
        self.assertEqual(self.run.review['decision'],'revision_required')
        calls=len(self.model.calls)
        with self.assertRaises(DomainError):self.step()
        self.assertEqual(len(self.model.calls),calls)

    def test_manual_edit_cannot_bypass_review_call_cap(self):
        self.until_review()
        for i in range(3):
            draft=dict(self.run.drafts[-1]['content']);draft['body']='用户修改版本'+str(i)
            self.run=self.store.command(self.run.run_id,'me',self.run.status_version,str(uuid4()),'edit',{'content':draft})
            self.step()
        self.assertEqual(self.run.run_status,'FAILED')
        self.assertEqual(self.model.calls.count('review'),3)

    def test_missing_material_then_supplement_rebuilds_snapshot(self):
        base=self.model.complete
        def need_material(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='research' and not json.loads(messages[1]['content'])['materials']:
                value.update(core_gap=True,gaps=['请提供真实经历'])
            return value,tokens
        self.run.context['material']=''
        with self.store.connect() as db:
            from dataclasses import asdict
            db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(asdict(self.run)),self.run.run_id))
        self.model.complete=need_material;self.step()
        self.assertEqual(self.run.wait_reason,'missing_material')
        self.run=self.store.command(self.run.run_id,'me',self.run.status_version,'supply','demo_supplement',{'material':'真实笔记','allow_hypothesis':True})
        self.assertNotEqual(self.run.snapshot_id,'snapshot');self.step()
        self.assertEqual(self.run.current_stage,'content')
        self.assertEqual(self.executor.public(self.run)['usage']['model_calls'],4)

    def test_daily_budget_applies_across_runs_and_owners(self):
        with self.store.connect() as db:
            db.execute("INSERT INTO live_calls(id,run_id,agent,stage,reserved,actual,state) VALUES('prior','another-owner-run','content','body',10000,10000,'received')")
        self.executor.config=Config('key',day_budget_usd=0.01)
        self.step();self.assertEqual(self.run.run_status,'FAILED');self.assertEqual(self.model.calls,[])

    def test_idempotency_and_new_key_old_version_cannot_charge_again(self):
        before=self.run;after=self.step(key='once')
        repeat=self.executor.step(before.run_id,'me',before.status_version,'once')
        self.assertEqual(after,repeat);self.assertEqual(len(self.model.calls),2)
        with self.assertRaises(DomainError):self.executor.step(before.run_id,'me',before.status_version,'other')
        self.assertEqual(len(self.model.calls),2)

    def test_failed_output_persists_consumption_and_never_falls_back(self):
        self.model.complete=lambda messages:({'bad':'output'},77)
        self.step();self.assertEqual(self.run.run_status,'FAILED');self.assertEqual(self.run.drafts,[])
        result=self.executor.public(self.run)
        self.assertGreater(result['usage']['tokens'],0)
        with self.assertRaises(DomainError):self.step()

    def test_transport_failure_keeps_unknown_usage_and_sanitizes_exception(self):
        def fail(messages):raise RuntimeError(self.config.api_key)
        self.model.complete=fail;self.step()
        result=view(self.run,self.executor)
        self.assertEqual(self.run.run_status,'FAILED');self.assertGreater(result['usage']['unknown_calls'],0)
        self.assertNotIn(self.config.api_key,json.dumps(result))

    def test_missing_key_and_tiny_budget_send_no_requests(self):
        self.executor.config=Config()
        with self.assertRaises(DomainError):self.step()
        self.assertEqual(self.model.calls,[])
        self.executor.config=Config('key',run_budget_usd=0.000001)
        self.step();self.assertEqual(self.model.calls,[]);self.assertEqual(self.run.run_status,'FAILED')

    def test_inflight_duplicate_restart_and_cancel_win(self):
        entered=threading.Event();release=threading.Event();base=self.model.complete
        def slow(messages):entered.set();release.wait(4);return base(messages)
        self.model.complete=slow
        before=self.run
        thread=threading.Thread(target=lambda:self.step(key='slow'));thread.start()
        self.assertTrue(entered.wait(2))
        current=self.store.get(before.run_id,'me')
        self.assertTrue(self.executor.public(current)['in_flight'])
        restarted=Executor(self.store,self.config,self.model)
        with self.assertRaises(DomainError):restarted.step(current.run_id,'me',current.status_version,'new')
        self.store.command(current.run_id,'me',current.status_version,'cancel','cancel')
        release.set();thread.join(5);self.assertFalse(thread.is_alive())
        self.assertEqual(self.store.get(before.run_id,'me').run_status,'CANCELLED')
        self.assertEqual(self.store.get(before.run_id,'me').drafts,[])

    def test_invalid_outline_stops_with_stage_name_and_no_extra_calls(self):
        base=self.model.complete
        def bad_outline(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='outline':value={'items':[{'title':'unexpected object'}]}
            return value,tokens
        self.model.complete=bad_outline
        self.step();self.step();self.step()
        self.assertEqual(self.run.run_status,'FAILED')
        self.assertEqual(len(self.model.calls),4)
        self.assertIn('提纲输出校验失败',self.run.events[-1]['payload']['message'])
        self.assertEqual(self.executor.public(self.run)['usage']['tokens'],480)

    def test_outline_compatibility_is_lossless_and_rejects_bad_fields(self):
        value={'items':[{'title':'归档','points':['按课命名','增加日期']},{'title':'复习','content':'每周检查'}]}
        self.assertEqual(normalize(self.run,'outline',value),['归档\n按课命名\n增加日期','复习\n每周检查'])
        for item in ({'title':'x','points':[123]},{'title':'x','content':'','ignored':'x'},''):
            with self.assertRaises(DomainError) as error:normalize(self.run,'outline',{'items':['valid',item]})
            self.assertIn('items[1]',str(error.exception))

    def test_recovery_reuses_successes_preserves_parent_and_costs(self):
        base=self.model.complete
        def fail_once(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='outline' and self.model.calls.count('outline')==1:value={'items':[None,'two']}
            return value,tokens
        self.model.complete=fail_once
        self.step();self.step();self.step();parent=self.run
        failed=self.executor.public(parent)['calls'][-1]
        self.assertEqual(failed['status'],'invalid');self.assertEqual(failed['diagnostic_response'],{'items':[None,'two']})
        self.assertIn('items[0]',failed['error'])
        with self.assertRaises(DomainError):self.executor.recover(parent.run_id,'other',parent.status_version)
        self.run=self.executor.recover(parent.run_id,'me',parent.status_version)
        self.assertEqual(self.run,self.executor.recover(parent.run_id,'me',parent.status_version))
        self.assertEqual(self.run.artifacts,parent.artifacts)
        for _ in range(5):self.step()
        self.assertEqual(self.run.wait_reason,'final_confirmation')
        self.assertEqual(self.model.calls.count('audience'),1)
        self.assertEqual(self.model.calls.count('strategy'),1)
        self.assertEqual(self.executor.public(self.run)['usage']['model_calls'],9)
        self.assertEqual(self.store.get(parent.run_id,'me'),parent)

    def test_recovery_cannot_reset_stage_cap_or_unknown_charges(self):
        base=self.model.complete
        def always_bad(messages):
            value,tokens=base(messages)
            if self.model.calls[-1]=='outline':value={'items':[None,'two']}
            return value,tokens
        self.model.complete=always_bad
        self.step();self.step();self.step()
        for _ in range(3):
            self.run=self.executor.recover(self.run.run_id,'me',self.run.status_version)
            self.step()
        self.assertEqual(self.model.calls.count('outline'),3)
        self.assertEqual(self.run.run_status,'FAILED')
        with self.store.connect() as db:db.execute("UPDATE live_calls SET actual=NULL WHERE stage='outline'")
        with self.assertRaises(DomainError):self.executor.recover(self.run.run_id,'me',self.run.status_version)

    def test_forged_quotes_and_wrong_title_blocked(self):
        value=schema('research');value['facts']=[{'source_id':'user-material','quote':'不存在的事实'}]
        with self.assertRaises(DomainError):normalize(self.run,'research',value)
        self.assertEqual(material_records(self.run.context)[0]['source_type'],'text')
        self.assertIsNone(material_records(self.run.context)[0]['page'])
        value=schema('title');value['selected']='不在候选中'
        with self.assertRaises(DomainError):normalize(self.run,'title',value)

    def test_config_literal_and_no_secret_public(self):
        path=Path(self.temp.name)/'.env';path.write_text('# comment\nDEEPSEEK_API_KEY="abc$def"\n', encoding='utf-8')
        cfg=load_config(path,{})
        self.assertEqual(cfg.api_key,'abc$def');self.assertNotIn('abc$def',repr(cfg)+json.dumps(cfg.public()))
        self.assertEqual(load_config(path,{'DEEPSEEK_API_KEY':'override'}).api_key,'override')
        self.assertFalse(load_config(Path(self.temp.name)/'absent',{}).ready)
        path.write_text('DEEPSEEK_API_KEY=a b', encoding='utf-8')
        with self.assertRaises(DomainError):load_config(path,{})

    def test_adapter_no_redirect_no_raw_error_and_json_validation(self):
        with self.assertRaises(DomainError):NoRedirect().redirect_request(None,None,None,None,None,None)
        packet={'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}],'usage':{'total_tokens':3}}
        self.assertEqual(decode_response(json.dumps(packet)),({'ok':True},3))
        packet['choices'][0]['finish_reason']='length'
        with self.assertRaises(DomainError):decode_response(json.dumps(packet))
        with patch('backend.provider.build_opener') as opener:
            opener.return_value.open.side_effect=HTTPError('https://api.deepseek.com',401,self.config.api_key,{},None)
            with self.assertRaises(DomainError) as caught:DeepSeek(self.config).complete([])
            self.assertNotIn(self.config.api_key,str(caught.exception))
            self.assertEqual(opener.return_value.open.call_count,1)

if __name__=='__main__':unittest.main()

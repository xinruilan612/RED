"""Regression for unlocated reviewer feedback and bounded re-audit input."""
import copy
import unittest
from backend.creator_context import model_operations
from backend.live import normalize, schema
from backend.review_grounding import located, project_previous
from backend.workflow import Run


class ReviewGroundingTests(unittest.TestCase):
    def run_fixture(self):
        run=Run('owner','snapshot',context={'mode':'live','material':'真实材料'})
        run.start()
        run.branch('audience','snapshot','succeeded',{'sample_size':0})
        run.branch('research','snapshot','succeeded',{'core_gap':False})
        run.join(True)
        run.draft({'selected_title':'标题','body':'真实正文','cta':'互动问题','tags':['学生鼠标','无线鼠标']})
        return run

    def test_unlocated_issue_cannot_approve_or_become_writer_instruction(self):
        run=self.run_fixture();raw=schema('review')
        raw['issues']=[dict(issue_id='phantom',severity='minor',state='open',location='body',
                            excerpt='从未出现在稿件里的虚构原句',reason='内部说明',suggestion='删除虚构原句')]
        before=copy.deepcopy(raw)
        report=normalize(run,'review',raw)
        self.assertEqual(raw,before)
        self.assertEqual(report['decision'],'revision_required')
        self.assertEqual(report['unlocated_issues'],raw['issues'])
        self.assertEqual(report['issues'][0]['issue_id'],'phantom')
        self.assertEqual(report['issues'][0]['state'],'open')
        self.assertEqual(next(c['result'] for c in report['checks'] if c['name']=='evidence_integrity'),'fail')
        writer=project_previous(report,run.drafts[-1]['content'],'revise')
        self.assertEqual(writer['issues'],[])
        self.assertNotIn('删除虚构原句',str(writer))
        self.assertNotIn('从未出现在稿件里的虚构原句',str(writer))
        self.assertEqual(writer['issues_requiring_recheck'][0]['issue_id'],'phantom')
        reviewer=project_previous(report,run.drafts[-1]['content'],'review')
        self.assertEqual(reviewer['issues_requiring_recheck'][0]['reason'],'内部说明')
        self.assertEqual(reviewer['issues_requiring_recheck'][0]['previous_excerpt'],'从未出现在稿件里的虚构原句')
        self.assertIsNone(run.accepted_ref)

    def test_legacy_issue_recheck_keeps_identity_without_assuming_resolved(self):
        run=self.run_fixture()
        report={'decision':'revision_required','issues':[
            dict(issue_id='old',location='body',excerpt='旧审核幻觉',reason='原问题',suggestion='删除'),
            dict(issue_id='real',location='tags',excerpt='学生鼠标',reason='表达',suggestion='具体化')],
            'limitations':['未实测']}
        before=copy.deepcopy(report)
        review=project_previous(report,run.drafts[-1]['content'],'review')
        self.assertEqual([i['issue_id'] for i in review['issues']],['real'])
        self.assertEqual(review['issues_requiring_recheck'][0]['issue_id'],'old')
        self.assertEqual(review['issues_requiring_recheck'][0]['previous_excerpt'],'旧审核幻觉')
        self.assertNotIn('result',review['issues_requiring_recheck'][0])
        self.assertEqual(report,before)

    def test_location_is_field_specific_and_tags_cannot_match_across_items(self):
        content=self.run_fixture().drafts[-1]['content']
        self.assertTrue(located({'location':'body','excerpt':'真实正文'},content))
        self.assertFalse(located({'location':'cta','excerpt':'真实正文'},content))
        self.assertTrue(located({'location':'tags','excerpt':'学生鼠标'},content))
        self.assertFalse(located({'location':'tags','excerpt':'学生鼠标\n无线鼠标'},content))
        self.assertFalse(located({'location':'body','excerpt':' '},content))

    def test_audit_projection_preserves_rules_and_snapshot_not_old_full_drafts(self):
        op={'platform':'xiaohongshu','profile':{'banned':['不虚构实测'],'tone':'自然'},
            'history':[{'title':'旧作品'}],'metrics':[{'views':10}],'competitors':['旧观察'],
            'memories':[{'text':'已确认经验'}],'active_hypothesis':{'statement':'待验证'},
            'preferences':[{'id':'p','source_type':'user_edit','changes':{'body':{'before':'旧稿'*3000,'after':'改稿'*3000}},
                            'interpretation':'表达偏好信号，不是规则'},
                           {'id':'explicit','source_type':'explicit','rule':'禁用夸张词'}]}
        before=copy.deepcopy(op)
        for stage in ('review','revise'):
            projected=model_operations(op,stage)
            self.assertEqual(projected['profile'],op['profile'])
            self.assertEqual(projected['memories'],op['memories'])
            self.assertEqual(projected['active_hypothesis'],op['active_hypothesis'])
            self.assertEqual(projected['preferences'][0]['changed_fields'],['body'])
            self.assertEqual(projected['preferences'][1],op['preferences'][1])
            self.assertNotIn('改稿改稿',str(projected))
            self.assertNotIn('metrics',projected)
            self.assertEqual(op,before)
        self.assertEqual(model_operations(op,'audience'),op)

    def test_deleted_valid_old_issue_still_reaches_reviewer_for_resolution(self):
        from backend.live import messages_for
        run=self.run_fixture()
        run.context.update(topic='鼠标',audience='学生',tone='自然',allow_hypothesis=True)
        old=copy.deepcopy(run.drafts[0])
        report={'draft_ref':old['ref'],'issues':[dict(issue_id='valid-old',location='body',
            excerpt='真实正文',reason='具体化表达',suggestion='修改')],'decision':'revision_required'}
        run.prior_review=report
        new=copy.deepcopy(old);new.update(ref='new@1');new['content']['body']='已改好的第二版'
        run.drafts.append(new)
        before=copy.deepcopy(run.prior_review)
        _,data=messages_for(run,'review')
        self.assertEqual(data['required_previous_issue_ids'],['valid-old'])
        self.assertEqual(data['previous_review']['issues'],report['issues'])
        self.assertNotIn('issues_requiring_recheck',data['previous_review'])
        self.assertEqual(data['draft']['body'],'已改好的第二版')
        self.assertEqual(run.prior_review,before)

    def test_legacy_report_without_version_does_not_guess_invalid_location(self):
        report={'issues':[dict(issue_id='old',location='body',excerpt='可能属于旧稿',reason='检查')]}
        self.assertEqual(project_previous(report,None,'review'),report)

    def test_unlocated_quarantine_does_not_repair_malformed_issue_contract(self):
        from backend.contracts import DomainError
        run=self.run_fixture();raw=schema('review')
        raw['issues']=[dict(issue_id='bad',severity='invented',state='open',location='body',
                            excerpt='虚构句',reason='理由',suggestion='建议')]
        with self.assertRaises(DomainError):normalize(run,'review',raw)

    def test_profile_projection_keeps_current_rules_not_historical_versions(self):
        profile={'id':'a','revision':3,'name':'展示名','aliases':['旧名'],
                 'profile':{'banned':'禁编测试数据','positioning':'数码'},
                 'revisions':[{'profile':{'banned':'旧规则'*1000}}]}
        op={'profile':profile};before=copy.deepcopy(op)
        projected=model_operations(op,'review')
        self.assertEqual(projected['profile']['profile'],profile['profile'])
        self.assertEqual(projected['profile']['revision'],3)
        self.assertNotIn('revisions',projected['profile'])
        self.assertEqual(op,before)
        report={'issues':[],'limitations':['未实测','未实测','缺少尺寸来源']}
        self.assertEqual(project_previous(report,None,'review')['limitations'],['未实测','缺少尺寸来源'])
        self.assertEqual(len(report['limitations']),3)

    def test_unlocated_issue_preserves_required_human_evidence_gate(self):
        run=self.run_fixture();raw=schema('review')
        raw.update(decision='needs_human',next_action='request_human',human_questions=['请补充尺寸原文'])
        raw['issues']=[dict(issue_id='missing',severity='major',state='open',location='body',
                            excerpt='不存在的句子',reason='缺少依据',suggestion='补资料')]
        report=normalize(run,'review',raw)
        self.assertEqual(report['decision'],'needs_human')
        self.assertEqual(report['next_action'],'request_human')
        self.assertEqual(report['human_questions'],['请补充尺寸原文'])
        self.assertTrue(report['unlocated_issues'])

    def test_resolved_old_issue_does_not_need_to_exist_in_current_copy(self):
        run=self.run_fixture();raw=schema('review')
        run.prior_review={'issues':[dict(issue_id='old',severity='major',state='open')]}
        raw['issues']=[dict(issue_id='old',severity='major',state='resolved',location='body',
                            excerpt='已从正文删除的旧问题',reason='已核对解决',suggestion='无需修改')]
        raw['previous_issue_results']=[{'issue_id':'old','result':'resolved'}]
        report=normalize(run,'review',raw)
        self.assertEqual(report['decision'],'approved')
        self.assertNotIn('unlocated_issues',report)

    def test_quarantine_does_not_mask_invalid_decision_or_next_action(self):
        from backend.contracts import DomainError
        run=self.run_fixture()
        for decision,action in [('invented','revise'),('approved','revise')]:
            raw=schema('review');raw.update(decision=decision,next_action=action)
            raw['issues']=[dict(issue_id='bad',severity='major',state='open',location='body',
                                excerpt='不存在的句子',reason='理由',suggestion='建议')]
            with self.assertRaises(DomainError):normalize(run,'review',raw)

    def test_many_historical_edits_are_counted_without_repeating_old_drafts(self):
        op={'preferences':[{'id':str(i),'source_type':'user_edit',
             'changes':{'body':{'before':'旧稿','after':'新稿'}}} for i in range(10)]}
        before=copy.deepcopy(op);projected=model_operations(op,'review')
        self.assertEqual(len(projected['preferences']),1)
        self.assertEqual(projected['preferences'][0]['record_count'],10)
        self.assertEqual(projected['preferences'][0]['changed_fields'],['body'])
        self.assertEqual(op,before)

    def test_review_prompt_prevents_resolved_old_issues_from_becoming_open_again(self):
        from backend.live import messages_for
        run=self.run_fixture()
        run.context.update(topic='罗技鼠标',audience='大学生',tone='自然',allow_hypothesis=True)
        before=copy.deepcopy(run.__dict__)
        messages,_=messages_for(run,'review')
        instruction=messages[0]['content']
        self.assertIn('issues只列当前确实存在且需要处理的问题',instruction)
        self.assertIn('previous_issue_results中判为resolved的问题，不得以同一issue_id在issues中继续标open',instruction)
        self.assertIn('无需修改的内容，不是待处理问题',instruction)
        self.assertIn('不要为了通过而伪造解决',instruction)
        self.assertEqual(run.__dict__,before)

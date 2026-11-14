"""Draft excerpts and source quotes are separate verbatim provenance fields."""
import copy
import unittest
import test_live_provider as fixtures
from backend.contracts import DomainError
from backend.live import draft_text, messages_for, normalize, review_gates, schema, verify_quotes
from backend.review_recovery import conservative_review


class ReviewExcerptMappingTests(unittest.TestCase):
    setUp = fixtures.LiveTests.setUp
    tearDown = fixtures.LiveTests.tearDown
    step = fixtures.LiveTests.step
    until_review = fixtures.LiveTests.until_review

    def test_review_prompt_supplies_only_verbatim_current_draft_candidates(self):
        run = self.until_review()
        run.drafts[-1]['content']['body'] = '容量350ml、杯身304不锈钢。\n未提供保温时长，请以实测为准。'
        messages, data = messages_for(run, 'review')
        candidates = data['draft_excerpt_candidates']
        self.assertTrue(candidates)
        actual = draft_text(run.drafts[-1]['content'])
        self.assertTrue(all(item['text'] in actual for item in candidates))
        self.assertIn({'location': 'body', 'text': '容量350ml、杯身304不锈钢。'}, candidates)
        prompt = messages[0]['content']
        self.assertIn('不能从materials复制来源句当excerpt', prompt)
        self.assertIn('候选只是稿件定位，不证明事实成立', prompt)
        self.assertIn('两者不要求相同', prompt)
        self.assertTrue(all(len(item['text'])<=400 for item in candidates))
        self.assertEqual({item['location'] for item in candidates}, {'selected_title','body','cta','tags'})
        run.context['creation_classification']={'domains':['general'],'channel':'xiaohongshu','format':'note'}
        classified,_=messages_for(run,'review')
        self.assertIn('此限制不适用于excerpt',classified[0]['content'])
        self.assertIn('不得为规避校验删除事实映射后直接批准', prompt)

    def test_source_sentence_cannot_masquerade_as_draft_excerpt(self):
        quote = '轻行保温杯，容量350毫升，杯身为304不锈钢，标称重量210克，旋盖结构。'
        draft = '已知三项可核对硬参数：容量350ml、杯身304不锈钢、标称重量210g。旋盖结构明确。'
        sources = [{'source_id': 'kb:fixture', 'text': quote}]
        with self.assertRaises(DomainError) as caught:
            verify_quotes([{'excerpt': quote, 'source_id': 'kb:fixture', 'quote': quote}], sources, draft)
        self.assertEqual(str(caught.exception), '审核引用无法匹配当前稿件')
        claims = [{'excerpt': excerpt, 'source_id': 'kb:fixture', 'quote': source}
                  for excerpt, source in [('容量350ml', '容量350毫升'), ('标称重量210g', '标称重量210克')]]
        verify_quotes(claims, sources, draft)
        claims[0]['quote'] = '容量350ml'
        with self.assertRaises(DomainError):
            verify_quotes(claims, sources, draft)

    def test_review_reordered_whole_lines_are_exact_and_response_unchanged(self):
        run=self.until_review()
        lines=['2 英寸旋转屏','1000 尼特 OLED 屏','支持旋屏开拍']
        run.context['material']='\n'.join(lines)
        raw=schema('review')
        raw['claim_map']=[{'excerpt':'完整正文','source_id':'user-material','quote':'｜'.join(reversed(lines))}]
        before=copy.deepcopy(raw)
        report=normalize(run,'review',raw)
        self.assertEqual([i['quote'] for i in report['claim_map']],list(reversed(lines)))
        self.assertEqual(raw,before)
        # A claim that cannot be located verbatim is dropped and the review hands
        # the evidence question to a human; it never approves on a guess.
        raw['claim_map'][0]['quote']='2 英寸旋转屏｜不存在的参数'
        report=normalize(run,'review',raw)
        self.assertEqual(report['claim_map'],[])
        self.assertEqual(report['decision'],'needs_human')
        self.assertEqual(report['next_action'],'request_human')

    def test_generic_handoff_handles_incomplete_response_without_ai_checked_claims(self):
        run=self.until_review()
        for raw in (None,[],{'checks':[]},{'decision':'approved','claim_map':[{'excerpt':'不存在','quote':'猜测'}]}):
            with self.subTest(raw=raw):
                before=copy.deepcopy(raw)
                report=conservative_review(run,raw,DomainError('MODEL_OUTPUT_INVALID','无法定位或字段缺失'))
                self.assertEqual(report['decision'],'needs_human')
                self.assertEqual(report['next_action'],'request_human')
                self.assertEqual(report['claim_map'],[])
                self.assertTrue(all(c['result']=='unknown' for c in report['checks']))
                self.assertTrue(report['human_questions'])
                self.assertEqual(report['draft_ref'],run.drafts[-1]['ref'])
                self.assertEqual(raw,before)

    def test_generic_handoff_keeps_previous_issues_unresolved_and_records_input_refs(self):
        run=self.until_review()
        run.context['evidence']=[{'source_id':'sample:provided','text':'样例内容','evidence_role':'expression_reference'}]
        run.prior_review={'issues':[{'issue_id':'old','severity':'major','state':'open','location':'body',
            'excerpt':'完整正文','reason':'原问题','suggestion':'需要人工核对'}]}
        report=conservative_review(run,{'decision':'approved'},'审核字段缺失')
        self.assertEqual(report['previous_issue_results'],[{'issue_id':'old','result':'unresolved'}])
        self.assertEqual(report['issues'][0]['state'],'open')
        notes='；'.join(report['limitations'])
        self.assertIn('sample:provided',notes)
        self.assertIn('未证明模型采用',notes)
        self.assertIn('模型未提供可靠的逐项复核',notes)

    def test_generic_handoff_acknowledges_evidence_gap_without_weakening_version_gates(self):
        run=self.until_review()
        run.branches['research']['data']['core_gap']=True
        run.branches['research']['data']['gaps']=['需要真实原文']
        report=conservative_review(run,None,'模型输出必须为对象')
        self.assertTrue(all(review_gates(run,report).values()))
        raw=schema('review');raw.update(decision='needs_human',next_action='request_human',human_questions=['核对原文'],
                                       recovery_kind='conservative_handoff')
        with self.assertRaises(DomainError):normalize(run,'review',raw)
        run.snapshot_id='changed-snapshot'
        with self.assertRaises(DomainError):conservative_review(run,None,'模型输出必须为对象')

    def test_manually_recovered_draft_without_research_requires_unknown_handoff(self):
        run=self.until_review()
        before=copy.deepcopy(run.drafts[-1])
        run.branches={}
        with self.assertRaises(DomainError) as caught:normalize(run,'review',schema('review'))
        self.assertEqual(caught.exception.code,'REVIEW_GATE_FAILED')
        report=conservative_review(run,None,'人工恢复的稿件缺少研究结果')
        self.assertEqual(report['decision'],'needs_human')
        self.assertEqual(report['claim_map'],[])
        self.assertTrue(all(c['result']=='unknown' for c in report['checks']))
        self.assertIn('资料缺口状态未知','；'.join(report['limitations']))
        self.assertEqual(run.branches,{})
        self.assertEqual(run.drafts[-1],before)
        self.assertTrue(all(review_gates(run,report).values()))
        self.assertFalse(review_gates(run,{**report,'decision':'approved',
                            'next_action':'await_user_confirmation'})['no_unresolved_evidence_gap'])
        run.snapshot_id='changed-snapshot'
        with self.assertRaises(DomainError):conservative_review(run,None,'旧稿件')

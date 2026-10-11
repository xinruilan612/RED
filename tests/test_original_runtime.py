"""Unpaid tests of the actual model input and fact provenance gate."""
import json
import unittest
from types import SimpleNamespace
from backend.contracts import DomainError
from backend.live import messages_for, normalize, reference_record, factual_records, schema


class OriginalRuntimeTests(unittest.TestCase):
    def run_fixture(self, examples=True):
        records=[{'source_id':'method:1','text':'先提出问题再说明。','material_type':'method'},
                 {'source_id':'example:1','text':'我亲测一个月效果翻倍。','material_type':'example'},
                 {'source_id':'fact:1','text':'这款桌子长120厘米。','material_type':'fact'}]
        return SimpleNamespace(context={'topic':'书桌详情','audience':'租房人群','tone':'简洁',
            'allow_hypothesis':True,'material':'桌面为白色。','evidence':records,
            'word_count':500,'goal':'说明尺寸',
            'creation_classification':{'domains':['furniture'],'channel':'xiaohongshu','format':'product_detail'},
            'creation_retrieval':{'groups':{'methods':[records[0]],'examples':[records[1]] if examples else [],'facts':[records[2]]}}},
            branches={},artifacts=[],drafts=[],review=None,prior_review=None)

    def test_all_stages_receive_frozen_three_groups_and_user_requirements(self):
        run=self.run_fixture()
        for stage in ('audience','research','strategy','outline','hook','title','body'):
            messages,data=messages_for(run,stage)
            self.assertEqual(json.loads(messages[1]['content']),data)
            self.assertEqual(data['creation_classification']['format'],'product_detail')
            self.assertEqual(data['brief']['word_count'],500)
            self.assertEqual([s['source_id'] for s in data['creation_retrieval']['facts']],['user-material','fact:1'])
            self.assertIn('用户明确要求 → 适用的渠道与形式要求',messages[0]['content'])
            self.assertIn('不只做同义词替换',messages[0]['content'])
        self.assertNotIn('body约150至250字',messages_for(run,'body')[0][0]['content'])

    def test_factual_limits_override_title_promise_and_review_suggestions(self):
        run=self.run_fixture(examples=False)
        run.drafts=[{'content':{'selected_title':'待审核','body':'已有事实','cta':'核对','tags':[]}}]
        for stage in ('strategy','outline','hook','title','body','revise','review'):
            instruction=messages_for(run,stage)[0][0]['content']
            self.assertIn('事实真实性优先于标题吸引力和原有标题承诺',instruction)
            self.assertIn('优先缩小承诺或重写标题以匹配已有事实',instruction)
            self.assertIn('不把必要条件当充分条件',instruction)
            self.assertIn('审核建议本身也必须有事实依据',instruction)
            self.assertIn('revise可调整selected_title以降低过度承诺',instruction)
            self.assertIn('不拿未知规格或未测项目逐段占位',instruction)

    def test_review_keeps_current_facts_and_obligations_without_historical_audit_duplication(self):
        import copy
        run=self.run_fixture()
        current={'selected_title':'当前稿','body':'这款桌子长120厘米。','cta':'核对尺寸','tags':[]}
        run.drafts=[{'content':current}]
        previous={'decision':'revision_required','next_action':'revise',
            'issues':[{'issue_id':'current-1','excerpt':'旧句子','suggestion':'按已有事实重写'}],
            'human_questions':[],'reference_records':{'old_duplicate':'旧记录'*1000},
            'claim_map':[{'excerpt':'旧稿主张','source_id':'old-source'}],
            'checks':[{'name':'old-check','result':'fail'}],
            'previous_issue_results':[{'issue_id':'ancient-1','result':'resolved'}]}
        run.prior_review=previous;run.review=previous
        run.context['creation_retrieval'].update(filters={'facts':{'owner':'private-audit-owner','channel':None}},
            classification=run.context['creation_classification'],engine='vector',gaps=[])
        run.artifacts=[{'stage':'strategy','value':{'why_account':'采用方法按规格分段，不移植样例事实'}}]
        frozen=copy.deepcopy(run.context['creation_retrieval'])
        raw=copy.deepcopy(previous)
        for stage in ('review','revise'):
            _,data=messages_for(run,stage)
            self.assertEqual(set(data['previous_review']),{'decision','next_action','issues','human_questions'})
            self.assertEqual(data['previous_review']['issues'],previous['issues'])
            self.assertEqual(data['draft'],current)
            self.assertEqual(next(s['text'] for s in data['materials'] if s['source_id']=='fact:1'),'这款桌子长120厘米。')
            self.assertEqual(data['creation_retrieval']['examples'][0]['text'],'我亲测一个月效果翻倍。')
            if stage=='review':
                self.assertEqual(data['required_previous_issue_ids'],['current-1'])
                self.assertEqual(set(data['creation_retrieval']),{'methods','examples','facts','gaps'})
                self.assertEqual(data['creation_retrieval']['facts'],[{'source_id':'user-material'},{'source_id':'fact:1'}])
        self.assertEqual(previous,raw)
        self.assertEqual(run.context['creation_retrieval'],frozen)
        self.assertEqual(reference_record(run,[])['adoption_notes'],['采用方法按规格分段，不移植样例事实'])

    def test_fixable_editorial_leakage_uses_bounded_revision_with_known_facts(self):
        from backend.live import editorial_revision_allowed
        from backend.editorial_boundary import annotate_review
        run=self.run_fixture(examples=False)
        run.context['creation_retrieval']['groups']['facts'][0]['source_id']='kb:fact-1'
        run.branches={'research':{'data':{'core_gap':False}}}
        report=schema('review')
        content={'body':'素材里没有手感依据，请自行猜测。'}
        allowed=editorial_revision_allowed(run,report)
        self.assertTrue(allowed)
        result=annotate_review(report,content,allow_revision=allowed)
        self.assertEqual(result['decision'],'revision_required')
        self.assertEqual(result['next_action'],'revise')
        self.assertEqual(result['human_questions'],[])
        self.assertEqual(next(c['result'] for c in result['checks'] if c['name']=='usefulness_and_readability'),'fail')
        self.assertTrue(any(i['issue_id'].startswith('copy-boundary-') for i in result['issues']))
        self.assertEqual(report['decision'],'approved')
        for change in ('missing_facts','core_gap','unknown_core_gap','legacy','reviewer_requires_human'):
            import copy
            case=copy.deepcopy(run);review=copy.deepcopy(report)
            if change=='missing_facts':case.context['creation_retrieval']['groups']['facts']=[]
            if change=='core_gap':case.branches['research']['data']['core_gap']=True
            if change=='unknown_core_gap':case.branches={}
            if change=='legacy':del case.context['creation_classification']
            if change=='reviewer_requires_human':review.update(decision='needs_human',next_action='request_human',human_questions=['需要实际测试数据'])
            allowed=editorial_revision_allowed(case,review)
            self.assertFalse(allowed,change)
            result=annotate_review(review,content,allow_revision=allowed)
            self.assertEqual(result['decision'],'needs_human',change)
            self.assertTrue(result['human_questions'])

    def test_example_cannot_be_research_fact_even_if_verbatim(self):
        run=self.run_fixture()
        value={'core_gap':False,'gaps':[],'prohibited_claims':['example:1 仅借鉴结构'],
               'facts':[{'source_id':'example:1','quote':'我亲测一个月效果翻倍。'}]}
        with self.assertRaises(DomainError):normalize(run,'research',value)
        value['facts']=[{'source_id':'fact:1','quote':'这款桌子长120厘米。'}]
        self.assertEqual(normalize(run,'research',value)['facts'],value['facts'])

    def test_method_cannot_be_fact_and_example_gap_is_recorded(self):
        run=self.run_fixture(examples=False)
        value={'core_gap':False,'gaps':[],'prohibited_claims':[],
               'facts':[{'source_id':'method:1','quote':'先提出问题再说明。'}]}
        with self.assertRaises(DomainError):normalize(run,'research',value)
        audit=reference_record(run,[])
        self.assertTrue(audit['example_gap'])
        self.assertEqual(audit['groups']['examples'],[])
        self.assertEqual(audit['groups']['facts'],['user-material','fact:1'])

    def test_review_rejects_verbatim_sample_claim(self):
        run=self.run_fixture()
        run.drafts=[{'content':{'selected_title':'书桌','body':'效果翻倍','cta':'看看尺寸','tags':[]}}]
        review=schema('review')
        review['limitations']=['example:1 只供结构参考']
        review['claim_map']=[{'excerpt':'效果翻倍','source_id':'example:1','quote':'我亲测一个月效果翻倍。'}]
        with self.assertRaises(DomainError):normalize(run,'review',review)

    def test_web_bodies_join_facts_only_when_topic_and_product_match(self):
        from backend.web_research import attach_facts
        run=self.run_fixture(examples=False)
        run.context['topic']='F04书桌尺寸介绍'
        report={'status':'complete','sources':[
            {'source_id':'web:wrong','text':'F99书桌尺寸120厘米'},
            {'source_id':'web:right','text':'F04书桌尺寸120厘米'},
            {'source_id':'web:other','text':'F04唇釉持妆测试'}]}
        attach_facts(run.context,report)
        self.assertEqual([s['source_id'] for s in report['sources']],['web:right'])
        self.assertIn('web:right',[s['source_id'] for s in factual_records(run.context)])
        self.assertEqual(report['sources'][0]['classification']['channel'],'any')
        messages,data=messages_for(run,'research')
        self.assertIn('web:right',[s['source_id'] for s in data['materials']])
        self.assertNotIn('web:wrong',[s['source_id'] for s in data['materials']])

    def test_six_titles_keeps_selected_last_and_aligned_reasons_without_mutating_raw(self):
        import copy
        run=self.run_fixture(examples=False)
        value={'candidates':['题'+str(i) for i in range(6)],'selected':'题5',
               'reasons':['理由'+str(i) for i in range(6)],'note':'最后一个最适合任务'}
        raw=copy.deepcopy(value)
        actual=normalize(run,'title',value)
        self.assertEqual(actual['candidates'],['题0','题1','题2','题3','题5'])
        self.assertEqual(actual['reasons'],['理由0','理由1','理由2','理由3','理由5'])
        self.assertEqual(actual['selected'],'题5')
        self.assertEqual(value,raw)
        for invalid in (
            {**raw,'candidates':raw['candidates'][:4],'reasons':raw['reasons'][:4]},
            {**raw,'reasons':raw['reasons'][:5]},
            {**raw,'candidates':['题0']+raw['candidates'][:5]},
            {**raw,'selected':'不在列表'},
            {**raw,'candidates':['题'+str(i) for i in range(11)],'reasons':['理由']*11}):
            with self.subTest(invalid=invalid),self.assertRaises(DomainError):normalize(run,'title',invalid)

    def test_old_snapshot_preserves_legacy_evidence(self):
        run=self.run_fixture()
        del run.context['creation_classification']
        self.assertIn('example:1',[s['source_id'] for s in factual_records(run.context)])


if __name__=='__main__':unittest.main()

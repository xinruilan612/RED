import copy
import unittest
from backend.live import messages_for, normalize, schema
from backend.workflow import Run
from backend.contracts import DomainError


class FactualGroundingTests(unittest.TestCase):
    def run_value(self, body):
        run=Run('owner','snapshot',run_status='RUNNING',current_stage='content',
                context={'mode':'live','topic':'相机','audience':'摄影爱好者','tone':'自然','allow_hypothesis':True},
                branches={'research':{'data':{'core_gap':False}}})
        run.draft({'selected_title':'相机介绍','body':body,'cta':'你的拍摄需求是什么？','tags':[]})
        return run

    def test_screenshot_absence_and_false_search_claim_cannot_pass(self):
        run=self.run_value('截至目前，大疆官网、京东官方旗舰店、全球新闻稿及权威数码媒体，均无该型号的任何发布信息。Pocket 3（2023年9月发布），搭载1英寸传感器、4K60fps。')
        raw=schema('review');before=copy.deepcopy(raw)
        report=normalize(run,'review',raw)
        self.assertEqual(report['decision'],'needs_human')
        self.assertEqual(len(report['issues']),2)
        self.assertEqual(raw,before)
        self.assertEqual(next(c['result'] for c in report['checks'] if c['name']=='evidence_integrity'),'fail')

    def test_empty_or_failed_search_never_proves_unreleased(self):
        for status in ('not_requested','insufficient','failed','complete'):
            run=self.run_value('Pocket 4 Pro尚未发布。')
            run.context['web_research']={'enabled':True,'status':status,'sources':[]}
            self.assertEqual(normalize(run,'review',schema('review'))['decision'],'needs_human')

    def test_real_model_absence_titles_cannot_pass(self):
        for claim in ('大疆根本没出Pocket 4 Pro！','Pocket 4 Pro并不存在。','官网只有Pocket 4和4P。'):
            run=self.run_value(claim)
            self.assertEqual(normalize(run,'review',schema('review'))['decision'],'needs_human')

    def test_related_model_scope_preserves_uncertain_identity(self):
        run=self.run_value('按需选购。')
        run.context['web_research']={'enabled':True,'status':'complete','identity_limits':[{'message':'型号关系未知'}]}
        run.context['evidence']=[{'source_id':'web:1','text':'官方产品介绍','source_type':'web',
            'authority_hint':'official_candidate','title':'官方产品','url':'https://example.com'}]
        messages,data=messages_for(run,'strategy')
        self.assertEqual(data['writing_scope']['official_pages'][0]['title'],'官方产品')
        self.assertIn('未在本次有限页面',data['writing_scope']['forbidden_inference'])
        self.assertIn('根本没出',messages[0]['content'])

    def test_read_web_body_and_valid_full_claim_quote_can_pass(self):
        body='官方标价为2999元。'
        run=self.run_value(body)
        run.context['evidence']=[{'source_id':'web:1','source_type':'web','text':body}]
        raw=schema('review');raw['claim_map']=[{'source_id':'web:1','quote':body,'excerpt':body}]
        self.assertEqual(normalize(run,'review',raw)['decision'],'approved')

    def test_citation_of_product_name_does_not_cover_made_up_spec(self):
        run=self.run_value('相机支持4K60fps，售价2999元。')
        run.context['material']='相机支持视频。'
        raw=schema('review');raw['claim_map']=[{'source_id':'user-material','quote':'相机','excerpt':'相机'}]
        self.assertEqual(normalize(run,'review',raw)['decision'],'needs_human')

    def test_number_mismatch_is_never_approved(self):
        # The claim cannot be cited, so it is dropped and the draft is handed to a
        # human with the unsupported figure localised; approval is impossible.
        run=self.run_value('售价2999元。');run.context['material']='售价1999元。'
        raw=schema('review');raw['claim_map']=[{'source_id':'user-material','quote':'2999元','excerpt':'2999元'}]
        report=normalize(run,'review',raw)
        self.assertEqual(report['decision'],'needs_human')
        self.assertEqual(report['claim_map'],[])
        self.assertTrue(any('2999' in issue['excerpt'] for issue in report['issues']))

    def test_universal_search_claim_is_unsupported_even_with_matching_material(self):
        body='官网与权威数码媒体均无任何发布信息。'
        run=self.run_value(body);run.context['material']=body
        run.context['web_research']={'reads':[{'status':'read','url':'https://example.com'}]}
        raw=schema('review');raw['claim_map']=[{'source_id':'user-material','quote':body,'excerpt':body}]
        self.assertEqual(normalize(run,'review',raw)['decision'],'needs_human')

    def test_generic_advice_does_not_require_fabricated_citation(self):
        run=self.run_value('按自己的拍摄需求比较便携性与握持感，选适合自己的相机。')
        self.assertEqual(normalize(run,'review',schema('review'))['decision'],'approved')

    def test_interface_and_dimensions_cannot_establish_comfort_or_setup(self):
        for body in ('USB接口，插上就能用。','尺寸适合桌面，握感适中。','支持所有电脑。','我连续用了两周。'):
            run=self.run_value(body);run.context['material']='产品配有USB接口，尺寸约100毫米。'
            raw=schema('review');raw['claim_map']=[{'source_id':'user-material','quote':'USB接口','excerpt':'USB接口'}] if 'USB接口' in body else []
            report=normalize(run,'review',raw)
            self.assertEqual(report['decision'],'needs_human',body)
            self.assertTrue(report['issues'],body)

    def test_explicit_matching_use_record_is_not_automatically_rejected(self):
        for body in ('产品支持即插即用。','用户记录：我亲测，握感舒适。'):
            run=self.run_value(body);run.context['material']=body
            raw=schema('review');raw['claim_map']=[{'source_id':'user-material','quote':body,'excerpt':body}]
            self.assertEqual(normalize(run,'review',raw)['decision'],'approved')

    def test_uncertain_source_does_not_support_positive_experience_claim(self):
        run=self.run_value('插上就能用。');run.context['material']='未知是否插上就能用。'
        raw=schema('review');raw['claim_map']=[{'source_id':'user-material','quote':'未知是否插上就能用。','excerpt':'插上就能用。'}]
        self.assertEqual(normalize(run,'review',raw)['decision'],'needs_human')

    def test_uncertainty_and_reader_advice_are_not_experience_assertions(self):
        for body in ('是否即插即用，请购买前确认。','握感舒适与否建议到店体验。','没有实测记录，不能保证即插即用。'):
            self.assertEqual(normalize(self.run_value(body),'review',schema('review'))['decision'],'approved',body)

    def test_pilot_compatibility_and_load_guarantees_stay_unverified(self):
        for body in ('正面接口不支持视频输出或充电。','显示器可直连背面接口。','放笔记本加水杯完全够用。',
                     '关键参数未公开。','拧紧所有螺丝。'):
            run=self.run_value(body)
            run.context['material']='机身正面提供两个支持USB 3的USB-C口和耳机插孔。桌面最大承重10公斤。'
            self.assertEqual(normalize(run,'review',schema('review'))['decision'],'needs_human',body)
        run=self.run_value('提供两种连接方式。');run.context['material']='蓝牙与接收器两种连接方式。'
        run.drafts[-1]['content']['tags']=['多设备切换']
        from backend.workflow import digest
        run.drafts[-1]['content_hash']=digest(run.drafts[-1]['content'])
        self.assertEqual(normalize(run,'review',schema('review'))['decision'],'needs_human')

    def test_repeat_finding_cannot_be_resolved_without_repair(self):
        run=self.run_value('售价2999元。');first=normalize(run,'review',schema('review'));run.prior_review=first
        raw=schema('review');raw['previous_issue_results']=[{'issue_id':i['issue_id'],'result':'resolved'} for i in first['issues']]
        report=normalize(run,'review',raw)
        self.assertEqual(report['previous_issue_results'][0]['result'],'unresolved')

    def test_prompts_include_date_and_no_search_status(self):
        run=self.run_value('按需选购。')
        for stage in ('research','strategy','body','review'):
            messages,data=messages_for(run,stage)
            self.assertRegex(data['current_date'],r'^20\d\d-\d\d-\d\d$')
            self.assertEqual(data['web_research']['status'],'not_requested')
            self.assertIn('用户资料只是未独立核实的参考',messages[0]['content'])
            self.assertIn('搜索失败均不等于',messages[0]['content'])

class ModelWebBudgetTests(unittest.TestCase):
    def test_full_web_snapshot_stays_intact_while_messages_use_exact_bounded_text(self):
        run=Run('owner','snapshot',context={'mode':'live','topic':'相机','audience':'读者','tone':'清楚','allow_hypothesis':False,
            'web_research':{'enabled':True,'status':'complete'},'evidence':[
                {'source_id':f'web:{n}','source_type':'web','text':('相机参数原文。'*600),'authority_hint':'official_candidate' if n<2 else 'unverified_publisher'} for n in range(3)]})
        before=copy.deepcopy(run.context)
        _,data=messages_for(run,'research')
        self.assertLessEqual(sum(len(s['text']) for s in data['materials']),2000)
        original={s['source_id']:s['text'] for s in run.context['evidence']}
        self.assertTrue(all(s['text'] in original[s['source_id']] and s['excerpt_truncated'] for s in data['materials']))
        self.assertEqual(run.context,before)

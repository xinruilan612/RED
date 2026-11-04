"""Exact noncontiguous research quotations never weaken reviewer citations."""
import copy
import unittest
from backend.contracts import DomainError
from backend.live import normalize, schema
from backend.workflow import Run


class ResearchQuoteTests(unittest.TestCase):
    first='这款相机适合记录日常生活'
    last='使用前请阅读产品说明书'

    def run_value(self):
        return Run('owner','snapshot',context={'material':self.first+'。中间的来源原文不需要引用。'+self.last+'。'},
                   branches={'research':{'data':{'core_gap':False}}})

    def research(self, quote):
        value=schema('research');value['facts']=[{'source_id':'user-material','quote':quote}]
        return value

    def test_all_explicit_ellipsis_forms_split_into_exact_facts(self):
        for ellipsis in ('…','……','...'):
            with self.subTest(ellipsis=ellipsis):
                raw=self.research(self.first+ellipsis+self.last);before=copy.deepcopy(raw)
                result=normalize(self.run_value(),'research',raw)
                self.assertEqual(result['facts'],[{'source_id':'user-material','quote':self.first},
                                                  {'source_id':'user-material','quote':self.last}])
                self.assertEqual(raw,before)

    def test_changed_or_short_span_is_dropped_never_cited(self):
        # Contract: an unverifiable quote never becomes a fact, but it also no
        # longer kills the stage. The item is dropped and disclosed in gaps; if
        # nothing verifies, core_gap turns true.
        material=self.run_value().context['material']
        for quote in (self.first+'…请仔细阅读产品说明书',self.first+'…说明书',self.first+'…',
                      '…'+self.last,self.first+'，'+self.last):
            with self.subTest(quote=quote):
                result=normalize(self.run_value(),'research',self.research(quote))
                for fact in result['facts']:self.assertIn(fact['quote'],material)
                if not result['facts']:
                    self.assertTrue(result['core_gap']);self.assertTrue(result['gaps'])

    def test_parts_must_belong_to_same_cited_source(self):
        run=self.run_value();run.context['material']=self.first
        run.context['evidence']=[{'source_id':'web:other','text':self.last}]
        result=normalize(run,'research',self.research(self.first+'…'+self.last))
        # The spliced quote cannot be verified inside the cited source, so no part
        # of it is cited and nothing from web:other is presented as user-material.
        self.assertEqual(result['facts'],[])
        self.assertTrue(result['core_gap'])

    def test_existing_contiguous_quote_with_ellipsis_is_not_rewritten(self):
        run=self.run_value();quote=self.first+'……'+self.last;run.context['material']=quote
        self.assertEqual(normalize(run,'research',self.research(quote))['facts'],self.research(quote)['facts'])

    def test_unknown_source_is_dropped_and_expansion_over_cap_still_rejects(self):
        raw=self.research(self.first+'…'+self.last);raw['facts'][0]['source_id']='missing'
        result=normalize(self.run_value(),'research',raw)
        self.assertEqual(result['facts'],[]);self.assertTrue(result['core_gap'])
        raw=self.research('…'.join([self.first]*31))
        with self.assertRaises(DomainError):normalize(self.run_value(),'research',raw)

    def test_reviewer_explicit_spans_keep_strict_draft_mapping(self):
        run=self.run_value();run.run_status='RUNNING';run.current_stage='content'
        run.draft({'selected_title':'相机介绍','body':self.first,'cta':'你怎么看？','tags':[]})
        raw=schema('review');raw['claim_map']=[{'source_id':'user-material','quote':self.first+'…'+self.last,'excerpt':self.first}]
        before=copy.deepcopy(raw)
        report=normalize(run,'review',raw)
        self.assertEqual([i['quote'] for i in report['claim_map']],[self.first,self.last])
        self.assertEqual(raw,before)
        raw['claim_map'][0]['excerpt']='模型编造的稿件摘录'
        with self.assertRaises(DomainError):normalize(run,'review',raw)

    def test_audience_split_preserves_interpretation_and_raw_response(self):
        examples=[
            ['大疆刚发布Osmo Pocket4 Pro，标准版定价3799元；','主摄都是1英寸大底','长焦为1/1.28英寸传感器，F1.8大光圈'],
            ['Osmo Pocket 4P，双眸所见，皆成大片。全新一英寸广角主摄','新增 60mm 黄金中焦搭配 f/1.8 大光圈'],
            ['Osmo Pocket 4','1 英寸 CMOS & 4K/240fps[1]','2 倍无损变焦[4]'],
        ]
        for parts in examples:
            with self.subTest(parts=parts):
                run=self.run_value();run.context['material']='中间未引用内容。'.join(parts)
                raw=schema('audience');raw['observations']=[{'source_id':'user-material','quote':'...'.join(parts),
                                                            'interpretation':'仅用于测试的观察分析，不证明来源事实已独立核实'}]
                original=copy.deepcopy(raw)
                result=normalize(run,'audience',raw)
                self.assertEqual([item['quote'] for item in result['observations']],parts)
                self.assertTrue(all(item['interpretation']==original['observations'][0]['interpretation'] for item in result['observations']))
                self.assertEqual(raw,original)

    def test_audience_invalid_ellipsis_or_missing_interpretation_still_rejects(self):
        # Invalid fragments are dropped, never cited; a missing interpretation is
        # a structural error and still rejects the whole response.
        material=self.run_value().context['material']
        for quote in (self.first+'...错误拼接的产品参数',self.first+'...说明书'):
            raw=schema('audience');raw['observations']=[{'source_id':'user-material','quote':quote,'interpretation':'观察'}]
            result=normalize(self.run_value(),'audience',raw)
            for item in result['observations']:self.assertIn(item['quote'],material)
        raw=schema('audience');raw['observations']=[{'source_id':'user-material','quote':self.first+'...'+self.last,'interpretation':None}]
        with self.assertRaises(DomainError):normalize(self.run_value(),'audience',raw)

class VerifiedSourceLabelTests(unittest.TestCase):
    def test_only_verified_title_label_and_exact_body_can_split(self):
        from backend.live import expand_research_ellipses
        sentence='一英寸 CMOS 再度升级，实际正文内容在这里。'
        source={'source_id':'web:label','title':'Osmo Pocket 4 - 官网','text':sentence+'\nOsmo Pocket 4'}
        item={'source_id':'web:label','quote':'Osmo Pocket 4，'+sentence,'interpretation':'对应产品'}
        result=expand_research_ellipses([item],[source])
        self.assertEqual([r['quote'] for r in result],['Osmo Pocket 4',sentence])
        self.assertTrue(all(r['quote'] in source['text'] for r in result))
        bad={**item,'quote':'Osmo Pocket 5，'+sentence}
        self.assertEqual(expand_research_ellipses([bad],[source]),[bad])

class ExactWholeLineTests(unittest.TestCase):
    def setUp(self):
        self.lines=['2 英寸旋转屏','1000 尼特 OLED 屏','支持旋屏开拍']
        self.source={'source_id':'web:list','text':'\n'.join(self.lines)}

    def split(self,quote,source=None):
        from backend.live import expand_research_ellipses
        item={'source_id':'web:list','quote':quote,'interpretation':'仅观察拍摄功能'}
        before=copy.deepcopy(item)
        result=expand_research_ellipses([item],[source or self.source])
        self.assertEqual(item,before)
        return result

    def test_reordered_lists_with_explicit_separators_are_exact_spans(self):
        for separator in ('\n','\r\n','｜','|'):
            with self.subTest(separator=separator):
                result=self.split(separator.join(reversed(self.lines)))
                self.assertEqual([item['quote'] for item in result],list(reversed(self.lines)))
                self.assertTrue(all(item['interpretation']=='仅观察拍摄功能' for item in result))
                self.assertTrue(all(item['quote'] in self.source['text'] for item in result))

    def test_skipped_lines_can_be_selected_but_not_invented(self):
        source={'source_id':'web:list','text':'五维摇杆\n中间未引用的完整行\n8 向云台控制\n三击翻转镜头朝向'}
        result=self.split(' 五维摇杆｜8 向云台控制｜三击翻转镜头朝向 ',source)
        self.assertEqual([item['quote'] for item in result],['五维摇杆','8 向云台控制','三击翻转镜头朝向'])

    def test_partial_unmatched_short_empty_and_generic_punctuation_stay_invalid(self):
        source={**self.source,'text':self.source['text']+'\n短词'}
        for quote in ('英寸旋转屏｜支持旋屏开拍','2 英寸旋转屏｜不存在的参数',
                      '短词｜支持旋屏开拍','2 英寸旋转屏｜',
                      '2 英寸旋转屏\n\n支持旋屏开拍','2 英寸旋转屏，支持旋屏开拍'):
            with self.subTest(quote=quote):
                result=self.split(quote,source)
                self.assertEqual(len(result),1);self.assertEqual(result[0]['quote'],quote)
                from backend.live import verify_quotes
                with self.assertRaises(DomainError):verify_quotes(result,[source])

    def test_cross_source_lines_cannot_be_borrowed(self):
        from backend.live import expand_research_ellipses,verify_quotes
        other={'source_id':'web:other','text':'8 向云台控制'}
        item={'source_id':'web:list','quote':'2 英寸旋转屏｜8 向云台控制'}
        result=expand_research_ellipses([item],[self.source,other])
        self.assertEqual(result,[item])
        with self.assertRaises(DomainError):verify_quotes(result,[self.source,other])

    def test_invalid_field_types_remain_domain_validation_errors(self):
        from backend.live import expand_research_ellipses,verify_quotes
        for item in ({'source_id':[],'quote':'2 英寸旋转屏｜支持旋屏开拍'},
                     {'source_id':'web:list','quote':['2 英寸旋转屏','支持旋屏开拍']},
                     {'source_id':'web:list'},None):
            with self.subTest(item=item):
                result=expand_research_ellipses([item],[self.source])
                with self.assertRaises(DomainError):verify_quotes(result,[self.source])

    def test_already_exact_quotes_remain_single_unmodified_quotes(self):
        for quote in ('2 英寸旋转屏｜支持旋屏开拍','2 英寸旋转屏\n支持旋屏开拍'):
            source={**self.source,'text':quote}
            result=self.split(quote,source)
            self.assertEqual(len(result),1);self.assertEqual(result[0]['quote'],quote)

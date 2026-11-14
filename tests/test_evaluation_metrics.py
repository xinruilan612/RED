"""Offline metric checks for the three-arm comparison study; no model, no network."""
import unittest
from backend.evaluation import (aggregate, checkable_sentences, draft_text,
                                expected_point_coverage, fact_support_rate,
                                forbidden_claim_hits, overlap_ratio, score_draft, sentences)

DRAFT = {'selected_title': '石头扫地机器人买前必量3处',
         'body': '第一次买石头扫地机器人？先量这3处。\n基站摆放位置需要留出散热空间。\n沙发床底净高需高于整机高度 96mm。\n该型号续航长达 180 分钟，适合所有家庭。',
         'cta': '记下来', 'tags': ['#选购']}
REFS = ['整机高度 96mm，基站推荐摆放空间需留出散热与维护余地。']
ITEM = {'expected_points': ['基站摆放空间', '家具底部净高', '门槛厚度'],
        'forbidden_claims': ['续航\\s*\\d+\\s*分钟', '适合所有家庭']}


class TokenTests(unittest.TestCase):
    def test_sentences_split_on_chinese_and_latin_punctuation(self):
        self.assertEqual(sentences('第一句。第二句！第三句？\n第四句'),
                         ['第一句', '第二句', '第三句', '第四句'])

    def test_checkable_requires_a_quantity_or_model_token(self):
        picked = checkable_sentences('纯感受的一句话。这个型号 96mm 高。价格 1999 元。')
        self.assertEqual(len(picked), 2)
        self.assertNotIn('纯感受的一句话', picked)

    def test_overlap_ratio_bounds(self):
        self.assertEqual(overlap_ratio('', '任意内容'), 0.0)
        self.assertEqual(overlap_ratio('相同文本', '相同文本'), 1.0)
        self.assertLess(overlap_ratio('基站摆放空间', '沙发床底净高'), 0.5)


class FactSupportTests(unittest.TestCase):
    def test_unsupported_spec_is_flagged_and_supported_one_is_matched(self):
        result = fact_support_rate('沙发床底净高需高于整机高度 96mm。该型号续航长达 180 分钟。', REFS)
        self.assertEqual(result['total'], 2)
        by_sentence = {row['sentence']: row for row in result['evidence']}
        self.assertTrue(by_sentence['沙发床底净高需高于整机高度 96mm']['supported'])
        self.assertFalse(by_sentence['该型号续航长达 180 分钟']['supported'])
        self.assertEqual(result['rate'], 0.5)

    def test_literal_unit_token_counts_as_support_even_without_overlap(self):
        result = fact_support_rate('整机高度 96mm', ['无关材料 96mm 处有说明'])
        self.assertEqual(result['supported'], 1)

    def test_no_checkable_sentence_reports_null_rate(self):
        result = fact_support_rate('只是一些感受，没有任何数量。', REFS)
        self.assertEqual((result['total'], result['rate']), (0, None))

    def test_empty_references_never_support_anything(self):
        result = fact_support_rate('整机高度 96mm', [])
        self.assertEqual(result['supported'], 0)


class ForbiddenTests(unittest.TestCase):
    def test_detects_and_reports_the_matched_text(self):
        result = forbidden_claim_hits(DRAFT['body'], ITEM['forbidden_claims'])
        self.assertTrue(result['any_hit'])
        self.assertEqual([hit['match'] for hit in result['hits']], ['适合所有家庭'])

    def test_clean_draft_has_no_hit(self):
        self.assertFalse(forbidden_claim_hits('只讲实测尺寸。', ITEM['forbidden_claims'])['any_hit'])

    def test_disclaimer_mention_is_not_a_violation(self):
        # The draft is correctly saying the material lacks these facts; a naive
        # regex would score it as a forbidden claim.
        text = '雾桃B01唇釉无持妆时长、保湿效果等未提供数据，仅列已确认规格。'
        result = forbidden_claim_hits(text, ['持妆\\s*\\d+', '保湿效果'])
        self.assertFalse(result['any_hit'], result)
        self.assertEqual(len(result['disclaimed']), 1)
        self.assertEqual(result['disclaimed'][0]['pattern'], '保湿效果')

    def test_other_disclaimer_verbs_are_not_violations(self):
        # Observed in real drafts: 未引申 / 未标注 are disclaimers, not assertions.
        for text, pattern in (('该数据来自当前可查资料，未引申稳定性、抗风性或实拍表现。', '抗风'),
                              ('但未标注承重与耐水性能。', '耐水')):
            result = forbidden_claim_hits(text, [pattern])
            self.assertFalse(result['any_hit'], text)

    def test_bare_negation_does_not_excuse_an_assertion(self):
        result = forbidden_claim_hits('没有任何限制，这款抗风能力很强。', ['抗风'])
        self.assertTrue(result['any_hit'])

    def test_assertion_after_negation_still_counts(self):
        text = '没有夸大宣传，这款连续试用21天不沾杯。'
        result = forbidden_claim_hits(text, ['不沾杯'])
        self.assertTrue(result['any_hit'])

    def test_invalid_pattern_raises_instead_of_silently_passing(self):
        with self.assertRaises(ValueError):
            forbidden_claim_hits('任意正文', ['[未闭合'])


class CoverageTests(unittest.TestCase):
    def test_covered_and_uncovered_points_are_separated(self):
        result = expected_point_coverage(DRAFT['body'], ITEM['expected_points'])
        by_point = {row['point']: row for row in result['evidence']}
        self.assertTrue(by_point['基站摆放空间']['covered'])
        self.assertFalse(by_point['门槛厚度']['covered'])
        self.assertEqual(result['total'], 3)


class DraftTextTests(unittest.TestCase):
    def test_flattens_title_body_cta_and_tags(self):
        text = draft_text(DRAFT)
        for part in ('买前必量3处', '基站摆放位置', '记下来', '#选购'):
            self.assertIn(part, text)

    def test_non_dict_is_empty(self):
        self.assertEqual(draft_text(None), '')


class ScoreAndAggregateTests(unittest.TestCase):
    def test_score_draft_reports_length_and_all_three_metrics(self):
        score = score_draft(DRAFT, REFS, ITEM)
        self.assertEqual(score['chars'], len(DRAFT['body']))
        self.assertEqual(set(score), {'chars', 'fact_support', 'forbidden', 'coverage'})
        self.assertTrue(score['forbidden']['any_hit'])

    def test_aggregate_means_per_arm_and_ignores_null_metrics(self):
        first = score_draft(DRAFT, REFS, ITEM)
        clean = score_draft({'body': '基站摆放空间需要留出散热余地。'}, REFS, {'expected_points': ['基站摆放空间'], 'forbidden_claims': []})
        rows = [{'arm': 'C', 'score': first}, {'arm': 'C', 'score': clean}, {'arm': 'A', 'score': clean}]
        summary = aggregate(rows)
        self.assertEqual(summary['C']['n'], 2)
        self.assertEqual(summary['A']['n'], 1)
        self.assertEqual(summary['C']['forbidden_hit_rate'], 0.5)
        self.assertEqual(summary['A']['forbidden_hit_rate'], 0.0)
        self.assertIsNotNone(summary['C']['fact_support_rate'])

    def test_aggregate_of_nothing_is_empty(self):
        self.assertEqual(aggregate([]), {})


if __name__ == '__main__':
    unittest.main()

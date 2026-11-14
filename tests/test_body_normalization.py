"""Ingestion formatting: specs become quotable lines without rewriting data.

The model quotes what it sees. Official product pages expose a spec table as
alternating label/value lines, so a reordered or concatenated quote cannot be
matched verbatim. Normalization joins only a field label with the value that
follows it; values are never joined to each other and no character of a number,
unit or model name is changed.
"""
import copy
import unittest
from backend.contracts import DomainError
from backend.live import normalize, schema, verify_quotes
from backend.web_research import normalize_body
from backend.workflow import Run


class NormalizeBodyTests(unittest.TestCase):
    def test_label_and_value_become_one_contiguous_line(self):
        body = '商品尺寸\n深度\n28 厘米\n高度\n237 厘米\n宽度\n80 厘米'
        self.assertEqual(normalize_body(body),
                         '商品尺寸\n深度 28 厘米\n高度 237 厘米\n宽度 80 厘米')

    def test_a_value_is_never_used_as_the_label_for_the_next_value(self):
        # The old rule merged every short line into the previous one, producing
        # "深度 28 厘米 高度 237 厘米" and losing which value belonged to which field.
        body = '深度\n28 厘米\n237 厘米'
        self.assertEqual(normalize_body(body), '深度 28 厘米\n237 厘米')

    def test_section_heading_is_not_chained_to_the_first_spec(self):
        body = '商品尺寸\n深度 28 厘米\n高度 237 厘米'
        self.assertEqual(normalize_body(body), body)
        self.assertEqual(normalize_body(normalize_body(body)), body)

    def test_normalization_is_idempotent(self):
        body = '深度\n28 厘米\n高度\n237 厘米\n宽度\n80 厘米\n'
        once = normalize_body(body)
        self.assertEqual(normalize_body(once), once)

    def test_page_with_nothing_to_merge_is_returned_verbatim(self):
        body = 'QX 7 Pro 技术参数\n' + ''.join(
            '项目%d：参数%d，以页面测试条件为准。\n' % (index, index) for index in range(20))
        before = copy.deepcopy(body)
        self.assertEqual(normalize_body(body), body)
        self.assertEqual(body, before)

    def test_noise_lines_are_removed_but_data_lines_are_kept(self):
        body = '加入购物袋\n深度\n28 厘米\n扫码下载宜家APP\n高度\n237 厘米'
        self.assertEqual(normalize_body(body), '深度 28 厘米\n高度 237 厘米')

    def test_numbers_units_and_model_names_are_never_rewritten(self):
        body = '最大可承重\n100 公斤\n型号\nQX 7 Pro\n价格\n¥649.00'
        output = normalize_body(body)
        for value in ('100 公斤', 'QX 7 Pro', '¥649.00', '最大可承重 100 公斤'):
            self.assertIn(value, output)

    def test_normalized_specs_are_quotable_in_reordered_order(self):
        source = {'source_id': 'web:1', 'text': normalize_body(
            '商品尺寸\n深度\n28 厘米\n高度\n237 厘米\n宽度\n80 厘米')}
        # Each reordered field/value pair is now a whole source line, so the
        # existing whole-line expansion can cite it after expansion.
        verify_quotes([{'source_id': 'web:1', 'quote': '宽度 80 厘米'},
                       {'source_id': 'web:1', 'quote': '深度 28 厘米'}], [source])

    def test_audience_reordered_spec_quote_dropped_until_sources_are_normalized(self):
        raw = '商品尺寸\n深度\n28 厘米\n高度\n237 厘米\n宽度\n80 厘米'
        quote = '宽度 80 厘米\n深度 28 厘米\n高度 237 厘米'

        def audience_run(material):
            return Run('owner', 'snapshot', context={'material': material},
                       branches={'research': {'data': {'core_gap': False}}})

        value = schema('audience')
        value['observations'] = [{'source_id': 'user-material', 'quote': quote,
                                  'interpretation': '官网尺寸字段被重排后仍是逐字原文'}]
        # The unformatted table is the exact shape that rejected R02. It is not
        # cited: the observation is dropped and disclosed in basis, never guessed.
        dropped = normalize(audience_run(raw), 'audience', copy.deepcopy(value))
        self.assertEqual(dropped['observations'], [])
        self.assertIn('已剔除', dropped['basis'])
        result = normalize(audience_run(normalize_body(raw)), 'audience', copy.deepcopy(value))
        self.assertEqual([item['quote'] for item in result['observations']],
                         ['宽度 80 厘米', '深度 28 厘米', '高度 237 厘米'])
        self.assertTrue(all(item['interpretation'] == '官网尺寸字段被重排后仍是逐字原文'
                            for item in result['observations']))

    def test_unverifiable_spec_is_still_rejected(self):
        source = {'source_id': 'web:1', 'text': normalize_body('深度\n28 厘米')}
        with self.assertRaises(DomainError) as raised:
            verify_quotes([{'source_id': 'web:1', 'quote': '深度 38 厘米'}], [source])
        self.assertEqual(raised.exception.code, 'MODEL_OUTPUT_INVALID')


if __name__ == '__main__':
    unittest.main()

import json
from pathlib import Path
import tempfile
import unittest
from scripts.brand_blindtest import DIMENSIONS, generate, page, summarize

CASE = {'product': '鼠标', 'audience': '学生', 'goal': '了解', 'facts': ['USB 接收器'], 'sources': [{'title': '官方', 'url': 'https://example.com/product'}], 'constraints': ['不造价格']}


class BrandBlindtestTests(unittest.TestCase):
    def build(self, directory, **kwargs):
        return generate(CASE, '普通稿正文', '系统稿正文', directory, seed=19, **kwargs)

    def response(self, mapping, pid='P01'):
        answers = {'preference': 'A', 'preference_reason': '说清楚接口'}
        for label in ('A', 'B'):
            answers.update({label + '_' + key: '4' for key in DIMENSIONS})
            answers.update({label + '_message': 'USB 接收器', label + '_reason': '还想知道手感'})
        return {'participant': pid, 'draft_hashes': mapping['participants'][pid]['draft_hashes'], 'answers': answers}

    def test_balanced_randomized_mapping_and_independent_html(self):
        with tempfile.TemporaryDirectory() as d:
            mapping = self.build(d)
            self.assertEqual(len(mapping['participants']), 5)
            count = sum(v['labels']['A'] == 'system' for v in mapping['participants'].values())
            self.assertIn(count, (2, 3))
            for pid in mapping['participants']:
                text = (Path(d) / (pid + '-试读.html')).read_text()
                self.assertIn('普通稿正文', text)
                self.assertIn('系统稿正文', text)
                self.assertNotIn('ordinary_ai', text)
                self.assertNotIn('"system"', text)
                self.assertNotIn('fetch(', text)
                self.assertIn('URL.createObjectURL', text)
                self.assertEqual(text.count('<section>'), 2)
                self.assertIn('required', text)
            self.assertTrue((Path(d) / '主持人专用-不要发给试读者.json').is_file())
            self.assertIsNone(mapping['production']['system']['elapsed_seconds'])

    def test_html_escapes_draft_and_script_injection(self):
        text = page('P01', {'A': '</pre><script>alert(1)</script>', 'B': 'safe'}, CASE)
        self.assertIn('&lt;script&gt;alert', text)
        self.assertNotIn('</pre><script>alert', text)
        self.assertEqual(text.count('<script>'), 1)

    def test_real_partial_answers_preserve_reasons_and_missing_people(self):
        with tempfile.TemporaryDirectory() as d:
            mapping = self.build(d)
            result = summarize(mapping, [self.response(mapping)])
            self.assertEqual(result['sample_size'], 1)
            self.assertEqual(len(result['missing_participants']), 4)
            self.assertEqual(result['results'][0]['preference'], mapping['participants']['P01']['labels']['A'])
            self.assertEqual(result['results'][0]['reasons']['system']['reason'], '还想知道手感')
            self.assertEqual(result['scores']['system']['interest'], [4])
            empty = summarize(mapping, [])
            self.assertEqual(empty['sample_size'], 0)
            self.assertEqual(empty['scores']['system']['interest'], [])

    def test_duplicate_unknown_and_changed_draft_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            mapping = self.build(d)
            valid = self.response(mapping)
            with self.assertRaises(ValueError):
                summarize(mapping, [valid, valid])
            for change in ({'participant': 'fake'}, {'draft_hashes': {'A': 'fake', 'B': 'fake'}}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    summarize(mapping, [dict(valid, **change)])

    def test_bad_or_missing_scores_and_reasons_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            mapping = self.build(d)
            for key, value in [('A_understand', '0'), ('B_interest', '6'), ('A_credible', ''), ('A_reason', ''), ('preference', 'system'), ('preference_reason', '')]:
                response = self.response(mapping)
                response['answers'][key] = value
                with self.subTest(key=key), self.assertRaises(ValueError):
                    summarize(mapping, [response])

    def test_prevent_overwrite_and_fake_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            self.build(d)
            with self.assertRaises(ValueError):
                self.build(d)
        for ordinary, system in [('', '稿'), ('稿', '稿')]:
            with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
                generate(CASE, ordinary, system, d)

    def test_missing_sources_and_invalid_production_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                generate(dict(CASE, sources=[]), '普通', '系统', d)
            production = {s: {'elapsed_seconds': float('nan')} for s in ('ordinary_ai', 'system')}
            with self.assertRaises(ValueError):
                self.build(d, production=production)

    def test_official_case_preserves_factual_boundaries(self):
        case = json.loads((Path(__file__).resolve().parents[1] / 'docs/evaluation/m185_case.json').read_text())
        self.assertEqual(case['sources'][0]['url'], 'https://www.logitech.com/zh-cn/shop/p/m185-wireless-mouse')
        self.assertIn('实际时间取决于使用方式和条件', ' '.join(case['facts']))
        self.assertIn('不代表品牌授权', ' '.join(case['constraints']))
        self.assertIn('不写静音', ' '.join(case['constraints']))


if __name__ == '__main__':
    unittest.main()

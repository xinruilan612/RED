"""Offline checks for the three-arm bench: gold-set validation, scoring, reporting."""
import json
import tempfile
import unittest
from pathlib import Path

from scripts.evaluation_bench import (GOLD, gold_set_hash, load_gold_set, score_results,
                                      self_check, validate_gold_set, write_report)

DRAFT = {'selected_title': '石头扫地机器人买前必量3处',
         'body': '基站摆放位置需要留出散热空间。\n沙发床底净高需高于整机高度 96mm。\n该型号续航长达 180 分钟，适合所有家庭。',
         'cta': '记下来', 'tags': ['#选购']}
ITEM = {'id': 'T01', 'topic': '测试选题', 'domain': 'digital', 'format': 'note',
        'expected_points': ['基站摆放空间'], 'forbidden_claims': ['适合所有家庭']}


def document(records):
    return {'items': [ITEM], 'records': records}


class GoldSetTests(unittest.TestCase):
    def test_shipped_gold_set_loads_and_validates(self):
        items = validate_gold_set(load_gold_set(GOLD))
        self.assertGreaterEqual(len(items), 7)
        for item in items:
            self.assertTrue(item['expected_points'])
            self.assertIsInstance(item['forbidden_claims'], list)

    def test_missing_required_field_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_gold_set({'items': [{'id': 'X', 'topic': 't', 'expected_points': ['a']}]})

    def test_duplicate_id_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_gold_set({'items': [ITEM, dict(ITEM)]})

    def test_invalid_forbidden_pattern_is_rejected_instead_of_crashing_later(self):
        with self.assertRaises(ValueError):
            validate_gold_set({'items': [{**ITEM, 'forbidden_claims': ['[未闭合']}]})

    def test_empty_expected_points_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_gold_set({'items': [{**ITEM, 'expected_points': []}]})

    def test_hash_tracks_content(self):
        base = {'items': [ITEM]}
        self.assertEqual(gold_set_hash(base), gold_set_hash({'items': [ITEM]}))
        self.assertNotEqual(gold_set_hash(base), gold_set_hash({'items': [{**ITEM, 'topic': '改了'}]}))


class ScoreResultsTests(unittest.TestCase):
    def test_stored_score_is_recomputed_not_trusted(self):
        doc = document([{'arm': 'C', 'item_id': 'T01', 'status': 'done', 'draft': DRAFT,
                         'references': ['整机高度 96mm'], 'score': {'chars': 99999}}])
        scored = score_results(doc)
        record = scored['records'][0]
        self.assertNotEqual(record['score']['chars'], 99999)
        self.assertTrue(record['score']['forbidden']['any_hit'])
        self.assertEqual(scored['summary']['C']['n'], 1)

    def test_unknown_item_id_fails_loudly(self):
        with self.assertRaises(KeyError):
            score_results(document([{'arm': 'A', 'item_id': 'NOPE', 'draft': {}}]))

    def test_failed_record_without_draft_scores_nothing(self):
        scored = score_results(document([{'arm': 'A', 'item_id': 'T01', 'status': 'failed', 'detail': '超时'}]))
        self.assertIsNone(scored['records'][0]['score']['fact_support']['rate'])


class ReportTests(unittest.TestCase):
    def test_report_lists_arms_metrics_and_failures(self):
        scored = score_results(document([
            {'arm': 'C', 'item_id': 'T01', 'status': 'done', 'draft': DRAFT, 'references': ['整机高度 96mm']},
            {'arm': 'A', 'item_id': 'T01', 'status': 'failed', 'detail': '模型超时', 'draft': {}}]))
        with tempfile.TemporaryDirectory() as folder:
            target = write_report(scored, Path(folder) / 'REPORT.md')
            text = target.read_text(encoding='utf-8')
        for heading in ('结论摘要', '逐条记录', '失败与缺失样本', '边界与限制'):
            self.assertIn(heading, text)
        self.assertIn('模型超时', text)
        self.assertIn('不是事实核查通过', text)
        self.assertIn('C 多Agent+分类检索', text)

    def test_report_states_when_no_failure_is_recorded(self):
        scored = score_results(document([{'arm': 'B', 'item_id': 'T01', 'status': 'done', 'draft': DRAFT}]))
        with tempfile.TemporaryDirectory() as folder:
            text = write_report(scored, Path(folder) / 'REPORT.md').read_text(encoding='utf-8')
        self.assertIn('若实验中确实出现过失败，此处为空即为报告缺陷', text)

    def test_empty_document_does_not_crash(self):
        with tempfile.TemporaryDirectory() as folder:
            text = write_report({'records': [], 'summary': {}}, Path(folder) / 'REPORT.md').read_text(encoding='utf-8')
        self.assertIn('尚无已判分记录', text)


class SelfCheckTests(unittest.TestCase):
    def test_self_check_covers_every_item_and_arm_without_cost(self):
        result = self_check(str(GOLD))
        self.assertEqual(result['records'], result['items'] * result['arms'])
        self.assertTrue(result['expected_points'] > 0)
        self.assertTrue(result['forbidden_patterns'] > 0)
        self.assertEqual(len(result['gold_set_hash']), 64)


if __name__ == '__main__':
    unittest.main()

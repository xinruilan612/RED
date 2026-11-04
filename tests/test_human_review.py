"""Blind-review kit: determinism, no arm leakage, and answer decoding."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_human_review import (SIDES, decode, load_pairs, shuffle_sides,
                                        write_answer_sheet, write_packet)

RESULTS = Path(__file__).resolve().parents[1] / 'docs/evidence/evaluation/results-20261018-221902.scored.json'


class PairTests(unittest.TestCase):
    def test_pairs_require_both_arms_and_have_body_text(self):
        pairs = load_pairs(RESULTS)
        self.assertGreaterEqual(len(pairs), 6)
        for pair in pairs:
            self.assertTrue(pair['A']['body'].strip())
            self.assertTrue(pair['C']['body'].strip())

    def test_sides_are_deterministic_and_balanced(self):
        pairs = load_pairs(RESULTS)
        first = shuffle_sides(pairs, seed=7)
        second = shuffle_sides(pairs, seed=7)
        self.assertEqual([r['left_arm'] for r in first], [r['left_arm'] for r in second])
        left = [r['left_arm'] for r in first]
        self.assertEqual(left.count('A'), len(pairs) // 2)
        for row in first:
            self.assertNotEqual(row['left_arm'], row['right_arm'])

    def test_packet_never_leaks_the_arm_label(self):
        rows = shuffle_sides(load_pairs(RESULTS))
        with tempfile.TemporaryDirectory() as folder:
            text = write_packet(rows, Path(folder) / 'PACKET.md').read_text(encoding='utf-8')
        for term in ('单次直写', '多 Agent', '多Agent', '分类检索', 'A 组', 'C 组', 'baseline'):
            self.assertNotIn(term, text)
        # Every item must appear exactly once with two readable versions.
        for row in rows:
            self.assertEqual(text.count(row['A']['body'].strip()[:30]) + text.count(row['C']['body'].strip()[:30]), 2)
        self.assertEqual(text.count('### 版本一'), len(rows))

    def test_answer_sheet_has_one_row_per_item(self):
        rows = shuffle_sides(load_pairs(RESULTS))
        with tempfile.TemporaryDirectory() as folder:
            path = write_answer_sheet(rows, Path(folder) / 'ANSWER_SHEET.csv')
            with path.open(encoding='utf-8-sig', newline='') as handle:
                table = list(csv.DictReader(handle))
        self.assertEqual(len(table), len(rows))
        self.assertEqual([row['题目ID'] for row in table], [r['item_id'] for r in rows])


class DecodeTests(unittest.TestCase):
    def test_answers_map_back_to_arms_via_the_key(self):
        rows = shuffle_sides(load_pairs(RESULTS))
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            key = {'sides': [{'item_id': r['item_id'], 'left_arm': r['left_arm'],
                              'right_arm': r['right_arm']} for r in rows]}
            (folder / 'key.json').write_text(json.dumps(key), encoding='utf-8')
            # Always answer 版本一; expect exactly one tally per arm per question
            # only when that arm sat on the left.
            csv_path = folder / 'answers.csv'
            with csv_path.open('w', encoding='utf-8-sig', newline='') as handle:
                writer = csv.writer(handle)
                writer.writerow(['读者编号', '组号', '题目ID',
                                 'Q1_哪版更容易看懂', 'Q2_哪版更可信', 'Q3_更愿意用哪版', '备注（可选）'])
                for index, row in enumerate(rows, start=1):
                    writer.writerow(['1', index, row['item_id'], '版本一', '版本一', '版本一', ''])
            target, tallies = decode(csv_path, folder / 'key.json', out_dir=folder)
            text = target.read_text(encoding='utf-8')
        expected_a = sum(1 for r in rows if r['left_arm'] == 'A')
        expected_c = sum(1 for r in rows if r['left_arm'] == 'C')
        self.assertEqual(tallies['Q1'].get('A', 0), expected_a)
        self.assertEqual(tallies['Q1'].get('C', 0), expected_c)
        self.assertIn('真人盲评结果', text)

    def test_tie_answers_are_counted_separately(self):
        rows = shuffle_sides(load_pairs(RESULTS))
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            key = {'sides': [{'item_id': r['item_id'], 'left_arm': r['left_arm'],
                              'right_arm': r['right_arm']} for r in rows]}
            (folder / 'key.json').write_text(json.dumps(key), encoding='utf-8')
            csv_path = folder / 'answers.csv'
            with csv_path.open('w', encoding='utf-8-sig', newline='') as handle:
                writer = csv.writer(handle)
                writer.writerow(['读者编号', '组号', '题目ID',
                                 'Q1_哪版更容易看懂', 'Q2_哪版更可信', 'Q3_更愿意用哪版', '备注（可选）'])
                for index, row in enumerate(rows, start=1):
                    writer.writerow(['2', index, row['item_id'], '差不多', '差不多', '都不愿意', ''])
            _, tallies = decode(csv_path, folder / 'key.json', out_dir=folder)
        self.assertEqual(tallies['Q1']['差不多'], len(rows))
        self.assertEqual(tallies['Q3']['都不愿意'], len(rows))


if __name__ == '__main__':
    unittest.main()


class HtmlPacketTests(unittest.TestCase):
    def test_html_is_self_contained_and_leaks_nothing(self):
        from scripts.build_human_review import write_html
        rows = shuffle_sides(load_pairs(RESULTS))
        with tempfile.TemporaryDirectory() as folder:
            text = write_html(rows, Path(folder) / 'PACKET.html').read_text(encoding='utf-8')
        self.assertEqual(text.count('<section class="card">'), len(rows))
        for term in ('单次直写', '多 Agent', '多Agent', '分类检索', 'A 组', 'C 组'):
            self.assertNotIn(term, text)
        # No external assets: it must open offline on a phone.
        self.assertNotIn('<link', text)
        self.assertNotIn('src="http', text)
        self.assertIn('虚构产品', text)

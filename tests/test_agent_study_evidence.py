"""Check delivered real-study evidence, separately from empty human templates."""
import csv
import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs/windtunnel/agent_study/evidence'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


class AgentStudyEvidenceTests(unittest.TestCase):
    def test_real_calls_and_unknown_reservation_reconcile_under_user_cap(self):
        summary = read(EVIDENCE / 'budget-summary.json')
        audit = read(EVIDENCE / 'budget-call-audit.json')
        known = sum(r['charged_upper_micro'] for r in audit if r['state'] == 'settled')
        unknown = sum(r['reserved_micro'] for r in audit if r['state'] != 'settled')
        self.assertEqual(len(audit), summary['calls'])
        self.assertEqual(known / 1e6, summary['charged_upper_cny'])
        self.assertEqual(unknown / 1e6, summary['reserved_unknown_cny'])
        self.assertLessEqual(known + unknown, 5_000_000)
        self.assertEqual(summary['unknown_calls'], 1)
        self.assertEqual(audit[-1]['state'], 'unknown')
        for row in audit:
            if row['state'] == 'settled':
                self.assertEqual(row['charged_upper_micro'],
                                 2 * row['input_tokens'] + 8 * row['output_tokens'])

    def test_six_distinct_codex_readers_complete_balanced_blind_assignment(self):
        with (ROOT / 'docs/windtunnel/templates/assignment_key_RESEARCHER_ONLY.csv').open() as f:
            mapping = {r['packet_id']: r for r in csv.DictReader(f)}
        provenance = read(EVIDENCE / 'reader-provenance.json')
        self.assertEqual(len({r['codex_agent'] for r in provenance}), 6)
        seen = Counter()
        for number in range(1, 7):
            folder = EVIDENCE / 'readers' / f'R{number:02}'
            tasks, answers = read(folder / 'tasks.json'), read(folder / 'responses.json')
            self.assertEqual(answers['participant_type'], 'codex_proxy')
            self.assertIsNone(answers['human_reading_seconds'])
            self.assertEqual(len(answers['responses']), 7)
            self.assertEqual({r['blind_id'] for r in answers['responses']},
                             {r['blind_id'] for r in tasks['tasks']})
            self.assertEqual(len({mapping[r['blind_id']]['sample_id'] for r in answers['responses']}), 7)
            for task in tasks['tasks']:
                data = (folder / (task['blind_id'] + '.txt')).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), task['manuscript_sha256'])
                seen[task['blind_id']] += 1
            self.assertEqual(provenance[number - 1]['fork_turns'], 'none')
            self.assertFalse(provenance[number - 1]['project_agent'])
        self.assertEqual(sum(seen.values()), 42)
        self.assertEqual(set(seen.values()), {3})

    def test_fallbacks_preserve_manuscripts_without_claiming_success(self):
        for sample in range(1, 11):
            for method in ('baseline', 'windtunnel'):
                folder = EVIDENCE / 'cases' / f'S{sample:02}' / method
                result = read(folder / 'result.json')
                self.assertEqual(hashlib.sha256((folder / 'final.txt').read_bytes()).hexdigest(),
                                 result['final_sha256'])
                if result['outcome'] != 'completed':
                    self.assertTrue(result['error'])
                    self.assertTrue(result['fallback'])
                if sample >= 6:
                    self.assertEqual(result['outcome'], 'failed')
                    self.assertFalse(result['changed'])
                    self.assertTrue(all(c['total_tokens'] is None or c['total_tokens'] == 0
                                        for c in result['calls']))

    def test_frozen_sources_and_rubric_have_the_recorded_hashes(self):
        freeze = read(EVIDENCE / 'freeze.json')
        for name, expected in freeze['code_hashes'].items():
            self.assertEqual(hashlib.sha256((EVIDENCE / 'frozen_source' / name).read_bytes()).hexdigest(), expected)
        rubric = ROOT / 'docs/windtunnel/agent_study/task_rubrics_candidate.json'
        self.assertEqual(hashlib.sha256(rubric.read_bytes()).hexdigest(), freeze['task_rubrics_sha256'])
        self.assertEqual(freeze['human_readers'], 0)

    def test_locked_scores_preserve_invalid_quotes_and_reconcile_analysis(self):
        lock = read(EVIDENCE / 'scoring-lock.json')
        scores = {}
        for letter in ('a', 'b'):
            path = EVIDENCE / f'scores_{letter}.json'
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), lock['hashes'][path.name])
            data = read(path)
            self.assertFalse(data['group_mapping_seen'])
            for row in data['scores']:
                self.assertEqual(len(row['points']), 5)
                self.assertTrue(all(p in (0, 1) for p in row['points']))
                self.assertEqual(row['score'], sum(row['points']))
                self.assertEqual(row['correct'], row['score'] == 5 and not row['contradiction'])
                key = (row['reader_id'], row['blind_id'])
                self.assertNotIn(key, scores)
                scores[key] = row
        invalid = 0
        for number in range(1, 7):
            folder = EVIDENCE / 'readers' / f'R{number:02}'
            response = read(folder / 'responses.json')
            for row in response['responses']:
                score = scores[(response['reader_id'], row['blind_id'])]
                text = (folder / (row['blind_id'] + '.txt')).read_text()
                for quote in row['evidence']:
                    if not quote['quote'] or quote['quote'] not in text:
                        invalid += 1
                        self.assertEqual(score['points'][quote['point'] - 1], 0)
        self.assertEqual(len(scores), 42)
        self.assertEqual(invalid, sum(r['non_exact_quotes'] for r in read(EVIDENCE / 'reader-provenance.json')))
        analysis = read(EVIDENCE / 'analysis-summary.json')
        self.assertEqual(sum(v['points'] for v in analysis['groups'].values()),
                         sum(r['score'] for r in scores.values()))
        self.assertFalse(analysis['causal_or_human_effect_claim'])


if __name__ == '__main__':
    unittest.main()

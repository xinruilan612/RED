"""Integrity of paid repair evidence, not an efficacy or human-user test."""
import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'docs/windtunnel/agent_study'
E = BASE / 'revision5/evidence'

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

class RepairEvidenceTests(unittest.TestCase):
    def test_seven_complete_pairs_and_exact_final_hashes(self):
        for number in range(4, 11):
            for method in ('baseline', 'windtunnel'):
                p = E / 'cases' / f'S{number:02}' / method
                r = read(p / 'result.json')
                self.assertEqual(r['outcome'], 'completed')
                self.assertEqual(r['final_sha256'], sha(p / 'final.txt'))
                if method == 'windtunnel':
                    self.assertEqual(len(r['final_report']['results']), 5)
                    self.assertEqual(r['unresolved_conditions'], [])
        r = read(E / 'cases/S04/windtunnel/result.json')
        self.assertTrue(r['effective_repair_confirmed'])
        self.assertGreater(r['patch_count'], 0)
        self.assertIn('[x*2 for x in vec if x >= 0]', (E / 'cases/S04/windtunnel/final.txt').read_text())

    def test_original_unknown_is_reserved_once_in_same_cumulative_ledger(self):
        rows = read(E / 'budget-call-audit.json')
        summary = read(E / 'budget-summary.json')
        known = sum(r['charged_upper_micro'] or 0 for r in rows)
        unknown = [r for r in rows if r['state'] != 'settled']
        self.assertEqual(len(rows), summary['calls'])
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0]['state'], 'unknown')
        self.assertEqual(unknown[0]['reserved_micro'], 42810)
        original = [r for r in read(BASE / 'evidence/budget-call-audit.json') if r['state'] == 'unknown'][0]
        self.assertEqual(unknown[0]['id'], original['id'])
        self.assertEqual(sum(r['messages_sha256'] == unknown[0]['messages_sha256'] for r in rows), 1)
        self.assertEqual(known / 1e6, summary['charged_upper_cny'])
        self.assertEqual((known + 42810) / 1e6, summary['committed_upper_cny'])
        self.assertLessEqual(known + 42810, 5_000_000)
        self.assertTrue(any(r['policy'] == 'legacy_native_bound_verified' for r in read(E / 'budget-policies.json')))

    def test_recovery_preserves_failure_and_known_raw_without_new_patch_request(self):
        old = read(E / 'controls/cases/S07/windtunnel/result.json')
        new = read(E / 'boundary-recovery/cases/S07/windtunnel/result.json')
        audit = read(E / 'boundary-recovery/recovery-audit.json')
        self.assertEqual(old['outcome'], 'failed')
        self.assertEqual(new['previous_failure'], old['error'])
        self.assertEqual(new['source_failed_result_sha256'], sha(E / 'controls/cases/S07/windtunnel/result.json'))
        before = [r['response'] for r in old['calls'] if r['stage'] == 'wt_patch']
        after = [r['response'] for r in new['calls'] if r['stage'] == 'wt_patch']
        self.assertEqual(before, after)
        self.assertEqual(len(before), 1)
        self.assertEqual(audit['new_recheck_requests'], 2)
        self.assertTrue(audit['known_patch_reused_without_new_request'])
        self.assertEqual(audit['recovery_script_sha256'], sha(E / 'boundary-recovery/recovery-script.py'))
        self.assertEqual(audit['model_router_sha256'], sha(E / 'boundary-recovery/frozen_source/backend/model_router.py'))

    def test_three_artificial_controls_repair_without_placeholder(self):
        definition = read(BASE / 'revision3/probe_inputs.json')
        self.assertEqual(definition['classification'], '人为删节缺口控制，非真实创作者')
        for sid in ('S06', 'S07', 'S10'):
            p = E / 'boundary-recovery/cases' / sid / 'windtunnel'
            r = read(p / 'result.json')
            self.assertTrue(r['changed'])
            self.assertTrue(r['effective_repair_confirmed'])
            self.assertGreater(r['patch_count'], 0)
            self.assertEqual(r['unresolved_conditions'], [])
            self.assertEqual(r['final_sha256'], sha(p / 'final.txt'))
            self.assertNotIn('待补充', (p / 'final.txt').read_text())
            patches = [c['response']['patches'] for c in r['calls'] if c['stage'] == 'wt_patch']
            self.assertTrue(all(p['citations'] for group in patches for p in group))

    def test_all_development_freezes_preserve_actual_source_bytes(self):
        paths = [BASE / f'revision{i}/evidence' for i in range(2, 6)]
        paths += [E / 'controls', E / 'boundary-recovery']
        for path in paths:
            for name, expected in read(path / 'freeze.json')['code_hashes'].items():
                self.assertEqual(sha(path / 'frozen_source' / name), expected)

    def test_six_fresh_readers_balanced_packets_and_locked_scores(self):
        folder = E / 'readers-study'
        frozen = read(folder / 'freeze_RESEARCHER_ONLY.json')
        for name, expected in frozen['packet_hashes'].items():
            self.assertEqual(sha(folder / name), expected)
        assignments = read(folder / 'assignment_key_RESEARCHER_ONLY.json')['assignments']
        self.assertEqual(set(Counter((a['sample_id'], a['variant']) for a in assignments).values()), {3})
        provenance = read(folder / 'reader-provenance.json')
        self.assertEqual(len({r['codex_agent'] for r in provenance}), 6)
        self.assertTrue(all(r['fork_turns'] == 'none' and not r['project_agent'] for r in provenance))
        scores = {}
        lock = read(folder / 'scoring-lock.json')
        for letter in ('a', 'b'):
            name = f'scores_{letter}.json'
            self.assertEqual(sha(folder / 'score_inputs' / name), lock['hashes'][name])
            data = read(folder / 'score_inputs' / name)
            self.assertFalse(data['group_mapping_seen'])
            for row in data['scores']:
                self.assertEqual(row['score'], sum(row['points']))
                self.assertEqual(row['correct'], row['score'] == 5 and not row['contradiction'])
                scores[(row['reader_id'], row['blind_id'])] = row
        invalid = quoted = 0
        for number in range(1, 7):
            reader = folder / 'readers' / f'R{number:02}'
            tasks = read(reader / 'tasks.json')['tasks']
            response = read(reader / 'responses.json')
            self.assertEqual(len(tasks), 3)
            self.assertIsNone(response['human_reading_seconds'])
            self.assertEqual({t['blind_id'] for t in tasks}, {a['blind_id'] for a in response['responses']})
            for answer in response['responses']:
                score = scores[(response['reader_id'], answer['blind_id'])]
                text = (reader / (answer['blind_id'] + '.txt')).read_text()
                for point in answer['points']:
                    flags = [bool(q) and q in text for q in point['evidence']]
                    quoted += len(flags)
                    invalid += sum(not f for f in flags)
                    if not flags or not all(flags):
                        self.assertEqual(score['points'][point['point'] - 1], 0)
        summary = read(folder / 'analysis-summary.json')
        self.assertEqual(len(scores), 18)
        self.assertEqual(quoted, summary['quoted_strings'])
        self.assertEqual(invalid, summary['non_exact_quotes'])
        self.assertEqual(sum(r['score'] for r in scores.values()), sum(g['points'] for g in summary['groups'].values()))
        self.assertFalse(summary['causal_or_human_effect_claim'])

if __name__ == '__main__':
    unittest.main()

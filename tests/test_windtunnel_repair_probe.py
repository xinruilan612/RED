import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_windtunnel_repair_probe as probe
from scripts.run_windtunnel_agent_study import StudyRunner, section


class RepairProbeTests(unittest.TestCase):
    def test_artificial_gaps_preserve_full_licensed_support_and_original_hashes(self):
        data = probe.load_inputs()
        originals = {s['sample_id']: s for s in json.loads((probe.PUBLIC / 'manifest.json').read_text())['samples']}
        absent_required = {'S06': ('encoding', 'readline', 'with', 'bytes'),
                           'S07': ('dumps', 'dump(', 'load(', 'pickle', 'utf-8'),
                           'S10': ('store_true', '--verbosity', '--verbose', '-v')}
        for case in data['cases']:
            sid = case['sample_id']
            original = originals[sid]
            self.assertEqual(case['classification'], probe.LABEL)
            self.assertEqual(case['language'], 'en')
            self.assertEqual(case['source_original_sha256'], original['draft_sha256'])
            self.assertEqual(case['support_sha256'], original['support_sha256'])
            self.assertEqual(case['support_path'], original['support_path'])
            draft = section(probe.PUBLIC / case['draft_path'])
            support = section(probe.PUBLIC / case['support_path'])
            self.assertLess(len(draft), 200)
            self.assertGreater(len(support), len(draft) * 5)
            self.assertNotEqual(draft, section(probe.PUBLIC / original['draft_path']))
            self.assertEqual(len(case['task']['expected_answer']), 5)
            for expected in case['task']['expected_answer']:
                self.assertNotIn(expected, draft)
            for concept in absent_required[sid]:
                self.assertNotIn(concept, draft)
            self.assertIn(probe.LABEL, (probe.PUBLIC / case['draft_path']).read_text())

    def test_six_cases_share_existing_ledger_and_freeze_precedes_calls(self):
        records = []
        data = probe.load_inputs()
        originals = {s['sample_id']: s for s in json.loads((probe.PUBLIC / 'manifest.json').read_text())['samples']}

        class FakeRunner:
            def __init__(self, workspace, **kwargs):
                records.append(('init', kwargs))
                self.samples = originals.copy()
                self.client = self

            def freeze(self):
                records.append(('freeze', self.samples, self.tasks))

            def run_case(self, sample_id, method):
                records.append(('call', sample_id, method))

            def summary(self):
                return {'cap_cny': 5, 'calls': 6}

        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / 'original-budget.sqlite'
            ledger.write_bytes(b'existing ledger marker')
            with patch.object(probe, 'StudyRunner', FakeRunner), contextlib.redirect_stdout(io.StringIO()):
                probe.main(['--workspace', temp, '--budget-ledger', str(ledger), '--authorize-live'])
            self.assertEqual(ledger.read_bytes(), b'existing ledger marker')
        kwargs = records[0][1]
        self.assertEqual(kwargs['budget_ledger'], ledger)
        self.assertTrue(kwargs['continue_after_unknown'])
        self.assertFalse(kwargs['atomic_conditions'])
        self.assertEqual(kwargs['revision'], 'v4.controlled')
        self.assertEqual(records[1][0], 'freeze')
        self.assertEqual(records[2:], [('call', sid, method) for sid in probe.IDS for method in ('baseline', 'windtunnel')])
        for case in data['cases']:
            sample = records[1][1][case['sample_id']]
            self.assertEqual(sample['support_path'], case['support_path'])
            self.assertEqual(sample['draft_path'], case['draft_path'])
            self.assertEqual(records[1][2][case['sample_id']], case['task'])

    def test_authorization_and_existing_ledger_are_required_before_runner(self):
        with patch.object(probe, 'StudyRunner') as runner, contextlib.redirect_stderr(io.StringIO()):
            for args in (['--workspace', '/tmp/probe', '--budget-ledger', '/tmp/missing-ledger'],
                         ['--workspace', '/tmp/probe', '--budget-ledger', '/tmp/missing-ledger', '--authorize-live'],
                         ['--workspace', '/tmp/probe', '--authorize-live']):
                with self.assertRaises(SystemExit):
                    probe.main(args)
            runner.assert_not_called()

    def test_repeat_existing_case_never_overwrites_or_resends(self):
        with tempfile.TemporaryDirectory() as temp:
            runner = object.__new__(StudyRunner)
            runner.workspace = Path(temp)
            folder = runner.workspace / 'cases/S06/windtunnel'
            folder.mkdir(parents=True)
            outcome = {'sample_id': 'S06', 'outcome': 'failed', 'error': 'unknown usage retained'}
            result = folder / 'result.json'
            result.write_text(json.dumps(outcome))
            final = folder / 'final.txt'
            final.write_text('preserved prior manuscript')
            self.assertEqual(runner.run_case('S06', 'windtunnel'), outcome)
            self.assertEqual(final.read_text(), 'preserved prior manuscript')
            self.assertEqual(json.loads(result.read_text()), outcome)


if __name__ == '__main__':
    unittest.main()

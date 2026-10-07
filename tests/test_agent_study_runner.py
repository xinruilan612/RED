"""Free study-runner regression checks: injected fake provider, never network/API.

The audit provider remains 'deepseek' because this exercises the project's
real routing/audit code; it is not evidence of a real DeepSeek model call.
"""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.contracts import DomainError
from backend.provider import Config
from scripts import run_windtunnel_agent_study as study


class FixtureAdapter:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def complete_result(self, messages):
        self.calls.append(messages)
        if self.fail:
            raise DomainError('PROVIDER_ERROR', 'Injected fixture failure, no API')
        system = messages[0]['content']
        data = json.loads(messages[1]['content'])
        if 'careful practical-tutorial editor' in system:
            value = dict(issues=[], revised_text=data['draft'])
        elif 'wt_conditions' in system:
            value = dict(conditions=[dict(question='Explain the tutorial example', scene='Python tutorial', source_ids=[], origin='author')])
        elif 'wt_read' in system:
            value = dict(results=[dict(condition_id=c['id'], status='unclear', answer='', excerpt='', reason='Fixture intentionally reports unclear') for c in data['conditions']])
        elif 'wt_verify' in system:
            value = dict(results=[dict(condition_id=c['id'], status='unclear', citations=[], reason='Fixture intentionally reports unclear') for c in data['conditions']], new_issues=[])
        elif 'wt_patch' in system:
            value = dict(patches=[])
        else:
            raise AssertionError('Unexpected fixture stage')
        return value, 3, dict(input_tokens=2, output_tokens=1, request_id='fixture-no-api')


class AgentStudyRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.adapter = FixtureAdapter()
        # Explicit Config bypasses .env; explicit adapter bypasses DeepSeek.
        self.runner = study.StudyRunner(self.workspace, Config('fixture'), self.adapter)

    def test_both_flows_preserve_original_with_empty_patch_and_audit(self):
        original = study.section(study.ROOT / 'docs/windtunnel/public_samples/S04/draft.md')
        for method, count in [('baseline', 1), ('windtunnel', 4)]:
            with self.subTest(method=method):
                result = self.runner.run_case('S04', method)
                self.assertEqual(result['outcome'], 'completed', result.get('error'))
                self.assertFalse(result['changed'])
                self.assertEqual(result['final_sha256'], study.sha(original))
                self.assertEqual((self.workspace / 'cases/S04' / method / 'final.txt').read_text(), original)
                self.assertEqual(len(result['calls']), count)
                for call in result['calls']:
                    self.assertEqual(call['provider'], 'deepseek')  # Routing label, fake adapter above.
                    self.assertEqual(call['model'], 'deepseek-flash')
                    self.assertEqual(call['input_tokens'], 2)
                    self.assertEqual(call['output_tokens'], 1)
                    self.assertEqual(call['total_tokens'], 3)
                if method == 'windtunnel':
                    self.assertEqual(result['patch_count'], 0)
        self.assertEqual(len(self.adapter.calls), 5)

    def test_completed_resume_never_resends(self):
        result = self.runner.run_case('S04', 'baseline')
        count = len(self.adapter.calls)
        self.assertEqual(self.runner.run_case('S04', 'baseline'), result)
        self.assertEqual(len(self.adapter.calls), count)

    def test_failed_run_preserves_original_and_resume_never_resends(self):
        self.adapter.fail = True
        result = self.runner.run_case('S04', 'baseline')
        self.assertEqual(result['outcome'], 'failed')
        self.assertEqual(result['error']['code'], 'PROVIDER_ERROR')  # Calls exposes a sanitized provider error.
        original = study.section(study.ROOT / 'docs/windtunnel/public_samples/S04/draft.md')
        self.assertEqual((self.workspace / 'cases/S04/baseline/final.txt').read_text(), original)
        self.assertEqual(result['budget']['unknown_calls'], 1)
        self.assertEqual(self.runner.run_case('S04', 'baseline'), result)
        self.assertEqual(len(self.adapter.calls), 1)

    def test_freeze_hash_change_blocks(self):
        self.runner.freeze()
        self.runner.freeze()
        with patch.object(study, 'BASELINE_PROMPT', study.BASELINE_PROMPT + '\nchanged'):
            with self.assertRaisesRegex(ValueError, 'Frozen inputs changed'):
                self.runner.freeze()

    def test_failed_windtunnel_preserves_draft_and_resume(self):
        self.adapter.fail = True
        result = self.runner.run_case('S04', 'windtunnel')
        self.assertEqual(result['outcome'], 'failed')
        original = study.section(study.ROOT / 'docs/windtunnel/public_samples/S04/draft.md')
        self.assertEqual((self.workspace / 'cases/S04/windtunnel/final.txt').read_text(), original)
        self.assertEqual(self.runner.run_case('S04', 'windtunnel'), result)
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(result['budget']['unknown_calls'], 1)

    def test_source_content_hashes_are_frozen_and_checked(self):
        self.runner.freeze()
        path = self.workspace / 'freeze.json'
        value = json.loads(path.read_text())
        self.assertEqual(len(value['input_file_hashes']), 20)
        source = next(iter(value['input_file_hashes']))
        value['input_file_hashes'][source] = 'changed-source-hash'
        study.write_json(path, value)
        with self.assertRaisesRegex(ValueError, 'Frozen inputs changed'):
            self.runner.freeze()

    def seed_cases(self, failed=False):
        for i in range(4, 11):
            for method in ['baseline', 'windtunnel']:
                folder = self.workspace / 'cases' / f'S{i:02}' / method
                folder.mkdir(parents=True)
                text = f'Neutral tutorial manuscript {i}'
                (folder / 'final.txt').write_text(text)
                study.write_json(folder / 'result.json', dict(outcome='failed' if failed and i == 4 and method == 'baseline' else 'completed', final_sha256=study.sha(text), error=dict(code='FIXTURE_FAILURE', message='Fake failure') if failed and i == 4 and method == 'baseline' else None, fallback='latest preserved draft; does not imply successful review' if failed and i == 4 and method == 'baseline' else None))

    def test_packets_contain_only_own_seven_texts_and_tasks(self):
        self.seed_cases()
        base = Path(self.runner.packets())
        with (study.ROOT / 'docs/windtunnel/templates/assignment_key_RESEARCHER_ONLY.csv').open() as handle:
            mapping = {r['packet_id']: r for r in csv.DictReader(handle)}
        for i in range(1, 7):
            reader = f'R{i:02}'
            folder = base / reader
            with (study.ROOT / f'docs/windtunnel/templates/reader_{reader}.csv').open() as handle:
                expected = list(csv.DictReader(handle))
            self.assertEqual({p.name for p in folder.iterdir()}, {'tasks.json'} | {r['packet_id'] + '.txt' for r in expected})
            data = json.loads((folder / 'tasks.json').read_text())
            self.assertEqual(data['participant_type'], 'codex_proxy')
            self.assertEqual(len(data['tasks']), 7)
            self.assertEqual([t['blind_id'] for t in data['tasks']], [r['packet_id'] for r in expected])
            for task in data['tasks']:
                self.assertEqual(set(task), {'blind_id', 'reading_order', 'task_prompt', 'manuscript_path', 'manuscript_sha256'})
                self.assertNotIn('expected_answer', task)
                self.assertNotIn('variant', task)
                self.assertNotIn('sample_id', task)
                file = Path(task['manuscript_path'])
                self.assertEqual(file.parent, folder)
                self.assertEqual(task['manuscript_sha256'], study.sha(file.read_text()))
                sample = mapping[task['blind_id']]['sample_id']
                self.assertEqual(task['task_prompt'], self.runner.tasks[sample]['task_prompt'])
        with self.assertRaises(ValueError):
            self.runner.packets()
        self.assertEqual(len(self.adapter.calls), 0)

    def test_incomplete_cases_cannot_generate_packets(self):
        with self.assertRaises((ValueError, FileNotFoundError, DomainError)):
            self.runner.packets()

    def test_documented_failure_fallback_is_kept_in_packets(self):
        self.seed_cases(failed=True)
        base = Path(self.runner.packets())
        self.assertTrue((base / 'R01/tasks.json').is_file())

    def test_missing_case_result_cannot_generate_packets(self):
        self.seed_cases()
        (self.workspace / 'cases/S04/baseline/result.json').unlink()
        with self.assertRaises((ValueError, FileNotFoundError, DomainError)):
            self.runner.packets()
        self.assertFalse((self.workspace / 'readers').exists())

    def test_modified_final_hash_cannot_generate_packets(self):
        self.seed_cases()
        (self.workspace / 'cases/S04/baseline/final.txt').write_text('tampered')
        with self.assertRaises((ValueError, DomainError)):
            self.runner.packets()
        self.assertFalse((self.workspace / 'readers').exists())


if __name__ == '__main__':
    unittest.main()

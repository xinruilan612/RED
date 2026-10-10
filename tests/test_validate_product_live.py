"""Offline wiring evidence only; no DeepSeek or external requests."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.contracts import DomainError
from backend.provider import Config
from scripts.study_budget import BudgetedClient
from scripts.validate_product_live import credential, exercise, main
from test_live_provider import FixtureModel


class Adapter:
    def __init__(self, *, unclear=False, unknown=False):
        self.base = FixtureModel(); self.calls = []; self.unclear = unclear; self.unknown = unknown

    def complete_result(self, messages):
        if self.unknown: raise RuntimeError('private credential never printed')
        data = json.loads(messages[1]['content']); system = messages[0]['content']
        if ' wt_read ' in system:
            self.calls.append('wt_read')
            rows = [{'condition_id': c['id'], 'status': 'unclear' if self.unclear else 'pass',
                     'answer': '' if self.unclear else '原目录，检查权限',
                     'excerpt_id': '' if self.unclear else data['reading_passages'][0]['excerpt_id'], 'reason': '测试替身'} for c in data['conditions']]
            value = {'results': rows}
        elif ' wt_verify ' in system:
            self.calls.append('wt_verify')
            value = {'results': [{'condition_id': c['id'], 'status': 'unclear' if self.unclear else 'pass', 'reason': '测试替身', 'citations': [] if self.unclear else [{'evidence_id': data['evidence_passages'][0]['evidence_id']}]} for c in data['conditions']], 'new_issues': []}
        elif ' wt_patch ' in system:
            self.calls.append('wt_patch'); value = {'patches': []}
        else:
            value, _ = self.base.complete(messages)
            self.calls.append(self.base.calls[-1])
        return value, 120, {'input_tokens': 100, 'output_tokens': 20, 'provider': 'fixture', 'model': 'fixture'}


class OneRevisionAdapter(Adapter):
    def complete_result(self, messages):
        value, tokens, meta = super().complete_result(messages)
        if self.calls[-1] == 'review' and self.calls.count('review') == 1:
            value.update(decision='revision_required', next_action='revise', issues=[{
                'issue_id': 'synthetic-revision', 'severity': 'major', 'state': 'open',
                'location': 'body', 'excerpt': '完整正文', 'reason': '需要具体说明', 'suggestion': '补充说明'}])
        return value, tokens, meta


class LiveValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)

    def tearDown(self): self.tmp.cleanup()

    def client(self, adapter):
        return BudgetedClient(adapter, self.root/'budget.sqlite', cap_cny=5)

    def test_once_no_ai_patch_is_not_claimed_and_no_hidden_edit(self):
        adapter = Adapter(); client = self.client(adapter)
        report = exercise(Config('fixture-only'), client, self.root/'result', export=False)
        self.assertEqual(report['outcome'], 'completed', report)
        self.assertEqual(report['ai_patch'], 'not_exercised')
        self.assertEqual(report['return_review'], 'not_exercised')
        self.assertEqual(report['user_edit'], 'not_exercised')
        self.assertTrue(report['synthetic_acceptance'])
        self.assertFalse(report['human_real_work_approved'])
        self.assertEqual(adapter.calls.count('wt_read'), 1)
        self.assertEqual(adapter.calls.count('wt_verify'), 1)
        with self.assertRaises(FileExistsError): exercise(Config('fixture-only'), client, self.root/'result', export=False)
        self.assertEqual(adapter.calls.count('wt_read'), 1)

    def test_explicit_edit_return_review_does_not_claim_ai_gain(self):
        adapter = Adapter(unclear=True); client = self.client(adapter)
        report = exercise(Config('fixture-only'), client, self.root/'edit', exercise_edit=True, export=False)
        self.assertEqual(report['outcome'], 'completed', report)
        self.assertEqual(report['return_review'], 'reviewed_and_synthetically_accepted')
        self.assertEqual(report['ai_patch'], 'not_exercised')
        self.assertEqual(report['user_edit'], 'explicit_synthetic_function_exercise')
        self.assertEqual(adapter.calls.count('review'), 2)
        self.assertEqual(adapter.calls.count('wt_patch'), 1)

    def test_parallel_worker_branches_are_serialized_until_settlement(self):
        import threading
        import time
        class SlowAdapter(Adapter):
            def __init__(self):
                super().__init__()
                self.guard = threading.Lock()
                self.active = self.max_active = 0
                self.branch_threads = set()
            def complete_result(self, messages):
                is_branch = '负责 audience 的' in messages[0]['content'] or '负责 research 的' in messages[0]['content']
                if not is_branch:
                    return super().complete_result(messages)
                with self.guard:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                    self.branch_threads.add(threading.get_ident())
                try:
                    # Ensure the other real Worker branch attempts entry before settlement.
                    time.sleep(.08)
                    return super().complete_result(messages)
                finally:
                    with self.guard: self.active -= 1
        adapter = SlowAdapter(); client = self.client(adapter)
        report = exercise(Config('fixture-only'), client, self.root/'parallel', export=False)
        self.assertEqual(report['outcome'], 'completed', report)
        self.assertEqual(adapter.calls.count('audience'), 1)
        self.assertEqual(adapter.calls.count('research'), 1)
        self.assertGreaterEqual(len(adapter.branch_threads), 2)
        self.assertEqual(adapter.max_active, 1)
        self.assertEqual(client.summary()['unknown_calls'], 0)
        self.assertEqual(client.summary()['calls'], len(adapter.calls))
        import sqlite3
        with sqlite3.connect(self.root/'parallel/study.sqlite') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM live_calls WHERE actual IS NULL').fetchone()[0], 0)

    def test_normal_paused_creation_continues_with_bounded_revision(self):
        adapter = OneRevisionAdapter(); client = self.client(adapter)
        report = exercise(Config('fixture-only'), client, self.root/'paused', export=False)
        self.assertEqual(report['outcome'], 'completed', report)
        self.assertEqual(report['normal_pause_continuations'], 1)
        self.assertEqual(adapter.calls.count('body'), 1)
        self.assertEqual(adapter.calls.count('revise'), 1)
        self.assertEqual(adapter.calls.count('review'), 2)
        self.assertEqual(client.summary()['unknown_calls'], 0)

    def test_returned_creation_normal_pause_is_advanced_without_initial_replay(self):
        class ReturnedRevisionAdapter(Adapter):
            def complete_result(self, messages):
                value, tokens, meta = super().complete_result(messages)
                if self.calls[-1] == 'review' and self.calls.count('review') == 2:
                    value.update(decision='revision_required', next_action='revise', issues=[{
                        'issue_id': 'returned-revision', 'severity': 'major', 'state': 'open',
                        'location': 'body', 'excerpt': '完整正文', 'reason': '说明需补足', 'suggestion': '补充说明'}])
                return value, tokens, meta
        adapter = ReturnedRevisionAdapter(); client = self.client(adapter)
        report = exercise(Config('fixture-only'), client, self.root/'returned-paused', exercise_edit=True, export=False)
        self.assertEqual(report['outcome'], 'completed', report)
        self.assertEqual(report['return_review'], 'reviewed_and_synthetically_accepted')
        self.assertEqual(report['normal_pause_continuations'], 1)
        self.assertEqual(adapter.calls.count('audience'), 1)
        self.assertEqual(adapter.calls.count('research'), 1)
        self.assertEqual(adapter.calls.count('body'), 1)
        self.assertEqual(adapter.calls.count('revise'), 1)
        self.assertEqual(adapter.calls.count('review'), 3)
        self.assertEqual(client.summary()['unknown_calls'], 0)

    def test_explicit_resume_preserves_failed_evidence_and_does_not_replay(self):
        from backend.service import Service
        adapter = OneRevisionAdapter(); client = self.client(adapter)
        original_background = Service.background
        starts = []
        def interrupt(service, owner, run_id, data):
            starts.append(data['action'])
            if len(starts) == 2:
                raise DomainError('VALIDATION_BLOCKED', '仅替身模拟旧harness停止在正常paused')
            return original_background(service, owner, run_id, data)
        directory = self.root/'resume-source'
        with patch.object(Service, 'background', interrupt):
            report = exercise(Config('fixture-only'), client, directory, export=False)
        self.assertEqual(report['error_code'], 'VALIDATION_BLOCKED', report)
        evidence = {p.name: p.read_bytes() for p in directory.glob('*.json')}
        count = client.summary()['calls']
        resumed = exercise(Config('fixture-only'), client, directory, export=False, resume=True)
        self.assertEqual(resumed['outcome'], 'completed', resumed)
        self.assertEqual(resumed['normal_pause_continuations'], 1)
        self.assertEqual(adapter.calls.count('audience'), 1)
        self.assertEqual(adapter.calls.count('research'), 1)
        self.assertEqual(adapter.calls.count('body'), 1)
        self.assertGreater(client.summary()['calls'], count)
        for name, raw in evidence.items(): self.assertEqual((directory/name).read_bytes(), raw)
        self.assertTrue(Path(resumed['resume_output']).joinpath('result.json').is_file())
        with self.assertRaises(FileExistsError):
            exercise(Config('fixture-only'), client, directory, export=False, resume=True)

    def test_unknown_stops_shared_ledger_without_replay(self):
        adapter = Adapter(unknown=True); client = self.client(adapter)
        report = exercise(Config('fixture-only'), client, self.root/'unknown', export=False)
        self.assertEqual(report['outcome'], 'blocked')
        self.assertEqual(client.summary()['unknown_calls'], 1)
        self.assertEqual(client.summary()['calls'], 1)
        again = exercise(Config('fixture-only'), client, self.root/'another', export=False)
        self.assertEqual(again['error_code'], 'STUDY_USAGE_UNKNOWN')
        self.assertEqual(client.summary()['calls'], 1)
        self.assertNotIn('private credential', (self.root/'unknown/result.json').read_text())

    def test_accepted_fixture_exports_full_copy_and_single_poster(self):
        import zipfile
        from PIL import Image
        adapter = Adapter(); client = self.client(adapter)
        report = exercise(Config('fixture-only'), client, self.root/'exports', export=True)
        self.assertEqual(report['outcome'], 'completed', report)
        with Image.open(self.root/'exports/synthetic-poster.png') as image:
            self.assertEqual(image.size, (1080, 1800))
        with zipfile.ZipFile(self.root/'exports/full-copy-images.zip') as bundle:
            self.assertIn('caption.txt', bundle.namelist())
            self.assertIn('完整正文', bundle.read('caption.txt').decode('utf-8'))
        self.assertIn('synthetic-poster.png', report['artifacts'])

    def test_credential_extracts_only_key_and_rejects_duplicate(self):
        file = self.root/'private.env'
        file.write_text('DATABASE_URL=do-not-use\nMODEL_ROUTES_JSON=do-not-use\nDEEPSEEK_API_KEY="fixture-only"\n')
        config = credential(file)
        self.assertEqual(config.api_key, 'fixture-only')
        self.assertFalse(config.routes)
        file.write_text('DEEPSEEK_API_KEY=first\nDEEPSEEK_API_KEY=second\n')
        with self.assertRaises(DomainError): credential(file)

    def test_cli_requires_existing_shared_ledger_before_adapter(self):
        with patch('scripts.validate_product_live.credential') as read_key, patch('builtins.print'):
            status = main(['--credential-file',str(self.root/'absent.env'),'--budget-ledger',str(self.root/'absent.sqlite'),'--output-dir',str(Path(__file__).resolve().parents[1]/'runtime/new-validation')])
        self.assertEqual(status, 1)
        read_key.assert_not_called()

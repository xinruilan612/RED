import concurrent.futures
from contextlib import closing
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.contracts import DomainError
from scripts.study_budget import BudgetedClient
from backend.provider import DeepSeek, Config


MESSAGES = [{'role': 'user', 'content': '中文'}]
RESERVE_MICRO = (len(json.dumps(MESSAGES, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')) + 1024)*2 + 3000*8


class Adapter:
    def __init__(self, meta=None, tokens=30, error=None):
        self.meta = {'input_tokens': 20, 'output_tokens': 10, 'request_id': 'req-1'} if meta is None else meta
        self.tokens, self.error, self.calls = tokens, error, 0

    def complete_result(self, messages):
        self.calls += 1
        if self.error:
            raise self.error
        return {'body': '模型正文'}, self.tokens, self.meta


class StudyBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'budget.sqlite3'

    def assert_code(self, code, function):
        with self.assertRaises(DomainError) as caught:
            function()
        self.assertEqual(caught.exception.code, code)

    def test_connection_is_closed_on_commit_and_rollback_without_garbage_collection(self):
        client = BudgetedClient(Adapter(), self.path)
        with client._connect() as committed:
            committed.execute("INSERT INTO study_budget_policy(policy) VALUES ('fixture-commit')")
        with self.assertRaises(sqlite3.ProgrammingError):
            committed.execute('SELECT 1')
        with self.assertRaisesRegex(ValueError, 'fixture'):
            with client._connect() as rolled_back:
                rolled_back.execute("INSERT INTO study_budget_policy(policy) VALUES ('fixture-rollback')")
                raise ValueError('fixture')
        with self.assertRaises(sqlite3.ProgrammingError):
            rolled_back.execute('SELECT 1')
        with client._connect() as db:
            values = [row[0] for row in db.execute('SELECT policy FROM study_budget_policy')]
        self.assertIn('fixture-commit', values)
        self.assertNotIn('fixture-rollback', values)

    def test_normal_metadata_settles_and_records(self):
        adapter = Adapter()
        client = BudgetedClient(adapter, self.path)
        value, tokens, meta = client.complete_result(MESSAGES)
        self.assertEqual((tokens, meta['input_tokens'], meta['output_tokens']), (30, 20, 10))
        self.assertEqual(client.summary(), {'cap_cny': 5, 'charged_upper_cny': .00012,
            'reserved_unknown_cny': 0, 'committed_upper_cny': .00012, 'calls': 1, 'unknown_calls': 0})
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute('SELECT messages_sha256,reserved_micro,charged_upper_micro,response_json,request_id FROM study_calls').fetchone()
        self.assertEqual(len(row[0]), 64)
        self.assertEqual(row[1:3], (RESERVE_MICRO, 120))
        self.assertEqual(json.loads(row[3]), value)
        self.assertEqual(row[4], 'req-1')

    def test_boundary_exact_and_over_cap_never_calls(self):
        adapter = Adapter()
        client = BudgetedClient(adapter, self.path, RESERVE_MICRO / 1_000_000)
        client.complete_result(MESSAGES)
        self.assert_code('STUDY_BUDGET_EXCEEDED', lambda: client.complete_result(MESSAGES))
        self.assertEqual(adapter.calls, 1)
        other = BudgetedClient(adapter, self.path.with_name('other.sqlite3'), (RESERVE_MICRO-1)/1_000_000)
        self.assert_code('STUDY_BUDGET_EXCEEDED', lambda: other.complete_result(MESSAGES))
        self.assertEqual(adapter.calls, 1)

    def test_invalid_usage_and_exception_block_followup(self):
        for i, adapter in enumerate((Adapter(meta={}), Adapter(tokens=31),
                Adapter(meta={'input_tokens': True, 'output_tokens': 29}),
                Adapter(meta={'input_tokens': 20, 'output_tokens': 3001}, tokens=3021),
                Adapter(error=RuntimeError('secret-api-key')))):
            path = self.path.with_name(f'unknown-{i}.sqlite3')
            client = BudgetedClient(adapter, path)
            self.assert_code('STUDY_BUDGET_UNKNOWN', lambda: client.complete_result(MESSAGES))
            self.assert_code('STUDY_BUDGET_UNKNOWN', lambda: client.complete_result(MESSAGES))
            reopened = BudgetedClient(Adapter(), path)
            self.assert_code('STUDY_BUDGET_UNKNOWN', lambda: reopened.complete_result(MESSAGES))
            self.assertEqual(adapter.calls, 1)
            self.assertEqual(reopened.summary()['reserved_unknown_cny'], RESERVE_MICRO / 1_000_000)
            self.assertNotIn(b'secret-api-key', path.read_bytes())

    def test_reopen_preserves_cap_and_consumption(self):
        client = BudgetedClient(Adapter(), self.path, RESERVE_MICRO / 1_000_000)
        client.complete_result(MESSAGES)
        self.assert_code('STUDY_BUDGET_INVALID', lambda: BudgetedClient(Adapter(), self.path, 5))
        reopened = BudgetedClient(Adapter(), self.path, RESERVE_MICRO / 1_000_000)
        self.assertEqual(reopened.summary(), client.summary())
        self.assert_code('STUDY_BUDGET_EXCEEDED', lambda: reopened.complete_result(MESSAGES))

    def test_concurrent_reservation_is_atomic_and_pending_blocks(self):
        entered, finish = threading.Event(), threading.Event()

        class BlockingAdapter(Adapter):
            def complete_result(self, messages):
                entered.set()
                if not finish.wait(5):
                    raise RuntimeError('test timeout')
                return super().complete_result(messages)

        adapter = BlockingAdapter()
        first = BudgetedClient(adapter, self.path, RESERVE_MICRO / 1_000_000)
        second = BudgetedClient(adapter, self.path, RESERVE_MICRO / 1_000_000)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(first.complete_result, MESSAGES)
            try:
                self.assertTrue(entered.wait(5))
                self.assert_code('STUDY_BUDGET_UNKNOWN', lambda: second.complete_result(MESSAGES))
                summary = second.summary()
                self.assertEqual(summary['calls'], 1)
                self.assertEqual(summary['committed_upper_cny'], summary['cap_cny'])
            finally:
                finish.set()
            future.result(timeout=5)
        self.assertEqual(adapter.calls, 1)
        self.assert_code('STUDY_BUDGET_EXCEEDED', lambda: second.complete_result(MESSAGES))

    def test_crash_reservation_cannot_be_retried(self):
        client = BudgetedClient(Adapter(), self.path)
        client._reserve(MESSAGES)
        reopened_adapter = Adapter()
        reopened = BudgetedClient(reopened_adapter, self.path)
        self.assert_code('STUDY_BUDGET_UNKNOWN', lambda: reopened.complete_result(MESSAGES))
        self.assertEqual(reopened_adapter.calls, 0)

    def test_cap_validation(self):
        for cap in (0, -1, 5.000001, 'NaN', 'Infinity', .0000001):
            self.assert_code('STUDY_BUDGET_INVALID', lambda: BudgetedClient(Adapter(), self.path, cap))

    def native_client(self, cap=5):
        return BudgetedClient(DeepSeek(Config(api_key='test-placeholder')), self.path, cap,
                              continue_after_unknown=True)

    def test_explicit_continue_keeps_unknown_reserve_and_never_replays(self):
        client = self.native_client()
        with patch.object(client.adapter, 'complete_result', side_effect=RuntimeError('secret-api-key')) as call:
            self.assert_code('STUDY_BUDGET_UNKNOWN', lambda: client.complete_result(MESSAGES))
            self.assert_code('STUDY_BUDGET_UNKNOWN', lambda: client.complete_result(MESSAGES))
            self.assertEqual(call.call_count, 1)
        other_messages = [{'role': 'user', 'content': 'different task'}]
        with patch.object(client.adapter, 'complete_result', side_effect=Adapter().complete_result):
            client.complete_result(other_messages)
        summary = client.summary()
        self.assertEqual(summary['calls'], 2)
        self.assertEqual(summary['unknown_calls'], 1)
        self.assertEqual(summary['committed_upper_cny'], (RESERVE_MICRO + 120) / 1_000_000)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT failure_code,continuation_safe FROM study_calls WHERE state='unknown'").fetchone(), ('ADAPTER_EXCEPTION', 1))
            self.assertIn(('continue_bounded_unknown',), db.execute('SELECT policy FROM study_budget_policy').fetchall())
        self.assertNotIn(b'secret-api-key', self.path.read_bytes())

    def test_continue_cap_includes_unknown_and_default_still_blocks(self):
        client = self.native_client(RESERVE_MICRO / 1_000_000)
        with patch.object(client.adapter, 'complete_result', side_effect=RuntimeError('private')):
            self.assert_code('STUDY_BUDGET_UNKNOWN', lambda: client.complete_result(MESSAGES))
        other = [{'role': 'user', 'content': 'next'}]
        with patch.object(client.adapter, 'complete_result') as call:
            self.assert_code('STUDY_BUDGET_EXCEEDED', lambda: client.complete_result(other))
            call.assert_not_called()
        default = BudgetedClient(Adapter(), self.path, RESERVE_MICRO / 1_000_000)
        self.assert_code('STUDY_BUDGET_UNKNOWN', lambda: default.complete_result(other))

    def test_continue_cannot_bypass_inflight_or_excess_usage(self):
        client = self.native_client()
        client._reserve(MESSAGES)
        other = [{'role': 'user', 'content': 'next'}]
        self.assert_code('STUDY_BUDGET_UNKNOWN', lambda: client.complete_result(other))
        self.path.unlink()
        client = self.native_client()
        oversized = ({}, 3020, {'input_tokens': 19, 'output_tokens': 3001})
        with patch.object(client.adapter, 'complete_result', return_value=oversized):
            self.assert_code('STUDY_BUDGET_UNKNOWN', lambda: client.complete_result(MESSAGES))
        self.assert_code('STUDY_BUDGET_UNKNOWN', lambda: client.complete_result(other))
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT failure_code,continuation_safe FROM study_calls').fetchone(), ('USAGE_BOUND_EXCEEDED', 0))

    def test_continuation_requires_native_verified_bounds_on_each_call(self):
        self.assert_code('STUDY_BUDGET_POLICY_INVALID', lambda: BudgetedClient(Adapter(), self.path, continue_after_unknown=True))
        self.assert_code('STUDY_BUDGET_POLICY_INVALID', lambda: BudgetedClient(DeepSeek(Config(model='other')), self.path, continue_after_unknown=True))
        client = self.native_client()
        for attribute, value in (('THINKING_TYPE', 'enabled'), ('MAX_OUTPUT_TOKENS', 3001)):
            with patch.object(client.adapter, attribute, value):
                self.assert_code('STUDY_BUDGET_POLICY_INVALID', lambda: client.complete_result(MESSAGES))
        self.assertEqual(client.summary()['calls'], 0)

    def test_legacy_unknown_requires_specific_audit_and_cannot_authorize_new_unsafe(self):
        old = BudgetedClient(Adapter(error=RuntimeError('private')), self.path)
        self.assert_code('STUDY_BUDGET_UNKNOWN', lambda: old.complete_result(MESSAGES))
        # Emulate a genuinely old ledger before failure classification existed.
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE study_calls SET failure_code=NULL')
            call_id = db.execute('SELECT id FROM study_calls').fetchone()[0]
        client = self.native_client()
        other = [{'role': 'user', 'content': 'new task'}]
        self.assert_code('STUDY_BUDGET_UNKNOWN', lambda: client.complete_result(other))
        client.authorize_legacy_unknown([call_id])
        with patch.object(client.adapter, 'complete_result', side_effect=Adapter().complete_result):
            client.complete_result(other)
        self.assertEqual(client.summary()['calls'], 2)
        self.assert_code('STUDY_BUDGET_POLICY_INVALID', lambda: client.authorize_legacy_unknown([call_id]))

    def test_untrusted_exception_codes_and_text_not_retained(self):
        client = self.native_client()
        with patch.object(client.adapter, 'complete_result', side_effect=DomainError('secret-code', 'secret-message')):
            self.assert_code('STUDY_BUDGET_UNKNOWN', lambda: client.complete_result(MESSAGES))
        self.assertNotIn(b'secret-code', self.path.read_bytes())
        self.assertNotIn(b'secret-message', self.path.read_bytes())

    def test_unbounded_message_features_rejected_before_request(self):
        client = self.native_client()
        invalid_messages = ([{'role': 'user', 'content': 'x', 'tools': []}],
                            [{'role': 'tool', 'content': 'x'}],
                            [{'role': 'user', 'content': [{'image': 'x'}]}])
        with patch.object(client.adapter, 'complete_result') as call:
            for messages in invalid_messages:
                self.assert_code('STUDY_BUDGET_INPUT_INVALID', lambda: client.complete_result(messages))
            call.assert_not_called()
        self.assertEqual(client.summary()['calls'], 0)


if __name__ == '__main__':
    unittest.main()

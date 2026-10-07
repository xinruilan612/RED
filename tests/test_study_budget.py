import concurrent.futures
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from backend.contracts import DomainError
from scripts.study_budget import BudgetedClient


MESSAGES = [{'role': 'user', 'content': '中文'}]
RESERVE_MICRO = (len('中文'.encode('utf-8')) + 1024)*2 + 3000*8


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

    def test_normal_metadata_settles_and_records(self):
        adapter = Adapter()
        client = BudgetedClient(adapter, self.path)
        value, tokens, meta = client.complete_result(MESSAGES)
        self.assertEqual((tokens, meta['input_tokens'], meta['output_tokens']), (30, 20, 10))
        self.assertEqual(client.summary(), {'cap_cny': 5, 'charged_upper_cny': .00012,
            'reserved_unknown_cny': 0, 'committed_upper_cny': .00012, 'calls': 1, 'unknown_calls': 0})
        with sqlite3.connect(self.path) as db:
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


if __name__ == '__main__':
    unittest.main()

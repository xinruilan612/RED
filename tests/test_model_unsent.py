"""Only proven pre-request failures release reservations and permit explicit retry."""
import unittest
from unittest.mock import patch
import test_live_provider as fixtures
from backend.contracts import DomainError
from backend.model_router import reconcile_unsent_calls

LEGACY = '模型地址解析到非公网网络，已停止'


class UnsentCallTests(unittest.TestCase):
    setUp = fixtures.LiveTests.setUp
    tearDown = fixtures.LiveTests.tearDown

    def invoke(self, reuse=True, text='same'):
        return self.executor.calls.invoke(self.run, 'audience', 'audience',
            [{'role': 'user', 'content': text}], lambda db: None, reuse=reuse)

    def fail(self, error, text='same'):
        with patch.object(self.executor.router, 'complete', side_effect=error) as complete:
            with self.assertRaises(DomainError) as caught:
                self.invoke(text=text)
            complete.assert_called_once()
        return caught.exception

    def test_unsent_calls_release_cost_and_attempts_then_explicit_retry_succeeds(self):
        for _ in range(5):
            error = self.fail(DomainError('MODEL_REQUEST_NOT_SENT', 'DNS unavailable'))
            self.assertEqual(error.code, 'MODEL_REQUEST_NOT_SENT')
        with self.store.connect() as db:
            rows = db.execute('SELECT c.state,c.actual,c.error,a.outcome FROM live_calls c JOIN model_audit a ON a.call_id=c.id').fetchall()
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(tuple(row) == ('not_sent', 0, 'DNS unavailable', 'not_sent') for row in rows))
        with patch.object(self.executor.router, 'complete', return_value=({'ok': True}, 10, {})) as complete:
            first = self.invoke()
            self.assertEqual(self.invoke(), first)
            complete.assert_called_once()

    def test_timeout_remains_unknown_and_never_repeats_call(self):
        self.fail(TimeoutError('unknown billed usage'))
        with patch.object(self.executor.router, 'complete') as complete:
            with self.assertRaises(DomainError) as caught:
                self.invoke()
            self.assertEqual(caught.exception.code, 'USAGE_UNKNOWN')
            complete.assert_not_called()
        with self.store.connect() as db:
            self.assertEqual(tuple(db.execute('SELECT state,actual FROM live_calls').fetchone()), ('failed', None))

    def test_any_unknown_attempt_blocks_even_when_received_attempt_exists(self):
        with patch.object(self.executor.router, 'complete', return_value=({'ok': True}, 10, {})):
            self.invoke()
        with patch.object(self.executor.router, 'complete', side_effect=TimeoutError()):
            with self.assertRaises(DomainError):
                self.invoke(reuse=False)
        with patch.object(self.executor.router, 'complete') as complete:
            with self.assertRaises(DomainError) as caught:
                self.invoke()
            self.assertEqual(caught.exception.code, 'USAGE_UNKNOWN')
            complete.assert_not_called()

    def test_legacy_reconciliation_is_precise_idempotent_and_preserves_audit(self):
        cases = [('exact', LEGACY, 'connection', None, None, 'failed'),
                 ('platform', LEGACY, None, None, None, 'failed'),
                 ('different', LEGACY + '!', 'connection', None, None, 'failed'),
                 ('known', LEGACY, 'connection', 10, None, 'failed'),
                 ('response', LEGACY, 'connection', None, '{}', 'failed'),
                 ('unaudited', LEGACY, 'connection', None, None, 'calling')]
        for name, error, connection, actual, response, outcome in cases:
            with self.store.connect() as db:
                db.execute("INSERT INTO live_calls(id,run_id,agent,stage,reserved,state,error,actual,response_json) VALUES(?,?,?,?,?,'failed',?,?,?)",
                           (name, self.run.run_id, 'audience', 'audience', 2000, error, actual, response))
                db.execute('INSERT INTO model_audit(call_id,run_id,agent,stage,provider,model,route_version,prompt_version,input_hash,sources,snapshot_id,started,rate,outcome,connection_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (name, self.run.run_id, 'audience', 'audience', 'deepseek', 'example', 'route', 'prompt', name, '[]', 'snapshot', 0, .000001, outcome, connection))
        with self.store.connect() as db:
            before = [tuple(r) for r in db.execute('SELECT * FROM model_audit ORDER BY call_id').fetchall()]
        self.assertEqual(reconcile_unsent_calls(self.store, 'other-run'), 0)
        self.assertEqual(reconcile_unsent_calls(self.store, self.run.run_id), 1)
        self.assertEqual(reconcile_unsent_calls(self.store), 0)
        with self.store.connect() as db:
            self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM model_audit ORDER BY call_id').fetchall()], before)
            rows = db.execute('SELECT id,state,actual,error FROM live_calls').fetchall()
        for row in rows:
            if row[0] == 'exact':
                self.assertEqual(tuple(row[1:]), ('not_sent', 0, LEGACY))
            else:
                self.assertEqual(row[1], 'failed')


class UnsentWorkerRecoveryTests(unittest.TestCase):
    from test_durable_runtime import DurableTests as _Fixture
    setUp = _Fixture.setUp
    prepare = _Fixture.prepare
    tearDown = _Fixture.tearDown
    run_value = _Fixture.run_value
    start = _Fixture.start
    job = _Fixture.job

    def test_worker_recovers_only_after_user_restart_for_proven_unsent(self):
        from backend.worker import Worker
        with patch.object(self.model, 'complete', side_effect=DomainError('MODEL_REQUEST_NOT_SENT', '尚未发送')):
            self.start()
            Worker(self.service).once()
        self.assertEqual(self.job()['status'], 'blocked')
        self.assertEqual(self.model.calls, [])
        self.assertFalse(Worker(self.service).once())
        self.assertEqual(self.model.calls, [])
        self.start()
        Worker(self.service).once()
        self.assertEqual(self.run_value().run_status, 'WAITING_USER')
        self.assertEqual(self.run_value().wait_reason, 'final_confirmation')
        self.assertEqual(len(self.model.calls), 8)

    def test_worker_legacy_repair_does_not_run_until_explicit_user_restart(self):
        from backend.worker import Worker
        with patch.object(self.model, 'complete', side_effect=DomainError('PROVIDER_ERROR', LEGACY)):
            self.start()
            Worker(self.service).once()
        self.assertEqual(self.job()['status'], 'blocked')
        with self.store.connect() as db:
            db.execute('UPDATE model_audit SET connection_id=? WHERE run_id=?', ('legacy-connection', self.run_id))
        self.assertGreater(reconcile_unsent_calls(self.store, self.run_id), 0)
        self.assertEqual(self.job()['status'], 'blocked')
        self.assertEqual(self.model.calls, [])
        self.start()
        Worker(self.service).once()
        self.assertEqual(self.run_value().wait_reason, 'final_confirmation')
        self.assertEqual(len(self.model.calls), 8)


class ReceivedResponseRecoveryTests(unittest.TestCase):
    from test_durable_runtime import DurableTests as _Fixture
    setUp = _Fixture.setUp
    prepare = _Fixture.prepare
    tearDown = _Fixture.tearDown
    run_value = _Fixture.run_value
    start = _Fixture.start
    job = _Fixture.job

    def test_current_schema_can_revalidate_historical_invalid_outline_without_resending(self):
        import json
        from backend import live
        from backend.worker import Worker
        original_model = self.model.complete
        original_normalize = live.normalize
        outline = {'items': [{'title': '整理', 'points': ['按课程建立目录']}, {'title': '查找', 'points': ['按关键词检索笔记']}]}
        def structured(messages):
            value, tokens = original_model(messages)
            return (outline if self.model.calls[-1] == 'outline' else value), tokens
        def old_validator(run, stage, value):
            if stage == 'outline':
                raise DomainError('MODEL_OUTPUT_INVALID', '旧版仅支持字符串提纲')
            return original_normalize(run, stage, value)
        with patch.object(self.model, 'complete', side_effect=structured):
            with patch('backend.live.normalize', side_effect=old_validator):
                self.start(); Worker(self.service).once()
            self.assertEqual(self.job()['status'], 'blocked')
            with self.store.connect() as db:
                before = tuple(db.execute("SELECT id,response_json,actual,state FROM live_calls WHERE stage='outline'").fetchone())
            self.assertEqual(before[3], 'invalid')
            self.assertEqual(json.loads(before[1]), outline)
            self.start(); Worker(self.service).once()
        self.assertEqual(self.run_value().wait_reason, 'final_confirmation')
        self.assertEqual(self.model.calls.count('outline'), 1)
        with self.store.connect() as db:
            after = tuple(db.execute("SELECT id,response_json,actual,state FROM live_calls WHERE stage='outline'").fetchone())
        self.assertEqual(after[:3], before[:3])
        self.assertEqual(after[3], 'validated')

    def test_invalid_stored_outline_remains_blocked_without_any_model_retry(self):
        from backend.worker import Worker
        original_model = self.model.complete
        def malformed(messages):
            value, tokens = original_model(messages)
            return ({'items': [123, 456]} if self.model.calls[-1] == 'outline' else value), tokens
        with patch.object(self.model, 'complete', side_effect=malformed):
            self.start(); Worker(self.service).once()
            self.assertEqual(self.job()['status'], 'blocked')
            calls = list(self.model.calls)
            self.start(); Worker(self.service).once()
        self.assertEqual(self.job()['status'], 'blocked')
        self.assertEqual(self.model.calls, calls)
        self.assertIn('items', self.job()['error'])

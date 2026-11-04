"""Separate CNY hard budget for authorized study calls through Calls.

Peak DeepSeek rates: input 2 and output 8 microCNY/token. This adapter
assumes the project's non-thinking provider enforces max_tokens=3000.
The ledger is never a production testing_budget setting.
Unknown usage blocks by default. Explicit native-bound continuation retains
the full reservation and permits different new requests, never replay.
"""
import hashlib
import json
import sqlite3
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from backend.contracts import DomainError


class BudgetedClient:
    def __init__(self, adapter, ledger_path, cap_cny=5, *, continue_after_unknown=False):
        try:
            micro = Decimal(str(cap_cny)) * 1_000_000
            if not micro.is_finite() or micro != micro.to_integral_value() or not 0 < micro <= 5_000_000:
                raise ValueError
            self.cap_micro = int(micro)
        except (ValueError, InvalidOperation, TypeError):
            raise DomainError('STUDY_BUDGET_INVALID', '测试预算须为不超过5元的正数，精度不超过百万分之一元') from None
        self.adapter = adapter
        self.continue_after_unknown = bool(continue_after_unknown)
        if self.continue_after_unknown:
            self._check_bounded_adapter()
        self.ledger_path = Path(ledger_path)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS study_budget (id INTEGER PRIMARY KEY CHECK(id=1), cap_micro INTEGER NOT NULL)')
            db.execute('''CREATE TABLE IF NOT EXISTS study_calls (
                id TEXT PRIMARY KEY, messages_sha256 TEXT NOT NULL,
                reserved_micro INTEGER NOT NULL, charged_upper_micro INTEGER,
                state TEXT NOT NULL CHECK(state IN ('reserved','settled','unknown')),
                input_tokens INTEGER, output_tokens INTEGER, request_id TEXT,
                response_json TEXT, elapsed_seconds REAL)''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(study_calls)')}
            for name, declaration in (('continuation_safe', 'INTEGER NOT NULL DEFAULT 0'),
                                      ('failure_code', 'TEXT')):
                if name not in columns:
                    db.execute(f'ALTER TABLE study_calls ADD COLUMN {name} {declaration}')
            db.execute('''CREATE TABLE IF NOT EXISTS study_budget_policy (
                id INTEGER PRIMARY KEY AUTOINCREMENT, policy TEXT NOT NULL, call_id TEXT)''')
            db.execute('INSERT INTO study_budget_policy(policy) VALUES (?)',
                       ('continue_bounded_unknown' if self.continue_after_unknown else 'stop_after_unknown',))
            existing = db.execute('SELECT cap_micro FROM study_budget WHERE id=1').fetchone()
            if existing is None:
                db.execute('INSERT INTO study_budget VALUES (1,?)', (self.cap_micro,))
            elif existing[0] != self.cap_micro:
                raise DomainError('STUDY_BUDGET_INVALID', '已有账本预算不可重置或修改')

    def _connect(self):
        return sqlite3.connect(str(self.ledger_path), timeout=30)

    def _check_bounded_adapter(self):
        from backend.provider import DeepSeek
        if (type(self.adapter) is not DeepSeek or self.adapter.config.model != 'deepseek-flash'
                or self.adapter.THINKING_TYPE != 'disabled' or self.adapter.MAX_OUTPUT_TOKENS != 3000):
            raise DomainError('STUDY_BUDGET_POLICY_INVALID', '继续未知调用仅适用于已核验的原生非思考 Flash 请求上限')

    def authorize_legacy_unknown(self, call_ids):
        """Explicit audited migration, never infer safety from missing old metadata.

        The caller must first verify these old calls used the original native
        Flash adapter with disabled thinking and the 3000-token output bound.
        """
        if not self.continue_after_unknown:
            raise DomainError('STUDY_BUDGET_POLICY_INVALID', '未启用有界未知调用继续策略')
        self._check_bounded_adapter()
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for call_id in call_ids:
                row = db.execute('SELECT state,failure_code,reserved_micro FROM study_calls WHERE id=?', (call_id,)).fetchone()
                if row is None or row[0] != 'unknown' or row[1] is not None or row[2] < 24000:
                    raise DomainError('STUDY_BUDGET_POLICY_INVALID', '仅可审核迁移原账本的未知有界请求')
                db.execute("UPDATE study_calls SET continuation_safe=1,failure_code='LEGACY_NATIVE_BOUND_VERIFIED' WHERE id=?", (call_id,))
                db.execute("INSERT INTO study_budget_policy(policy,call_id) VALUES ('legacy_native_bound_verified',?)", (call_id,))

    def _reserve(self, messages):
        encoded = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        if self.continue_after_unknown:
            self._check_bounded_adapter()
        # Include roles/framing as well as content, so many small messages do
        # not silently escape the byte-based conservative input bound.
        if (not isinstance(messages, list) or not messages or any(
                not isinstance(m, dict) or set(m) != {'role', 'content'}
                or m['role'] not in ('system', 'user', 'assistant')
                or not isinstance(m['content'], str) for m in messages)):
            raise DomainError('STUDY_BUDGET_INPUT_INVALID', '研究请求必须为普通文本消息')
        input_upper = len(encoded) + 1024
        reserve = input_upper * 2 + 3000 * 8
        call_id = str(uuid4())
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            # One paid request at a time, including across processes. A crash
            # leaves reserved state, which must never enable an automatic retry.
            blocked = (db.execute("SELECT 1 FROM study_calls WHERE state='reserved' OR (state='unknown' AND continuation_safe=0) LIMIT 1").fetchone()
                       if self.continue_after_unknown else db.execute("SELECT 1 FROM study_calls WHERE state!='settled' LIMIT 1").fetchone())
            if blocked:
                raise DomainError('STUDY_BUDGET_UNKNOWN', '已有调用在途或用量未知，已停止后续付费调用')
            fingerprint = hashlib.sha256(encoded).hexdigest()
            if db.execute("SELECT 1 FROM study_calls WHERE state='unknown' AND messages_sha256=? LIMIT 1", (fingerprint,)).fetchone():
                raise DomainError('STUDY_BUDGET_UNKNOWN', '同一未知请求禁止重发；可继续不同的新请求')
            used = db.execute("SELECT COALESCE(SUM(CASE WHEN state='settled' THEN charged_upper_micro ELSE reserved_micro END),0) FROM study_calls").fetchone()[0]
            if used + reserve > self.cap_micro:
                raise DomainError('STUDY_BUDGET_EXCEEDED', '本次保守预留将超过测试总额上限，未发起调用')
            db.execute('INSERT INTO study_calls(id,messages_sha256,reserved_micro,state) VALUES(?,?,?,?)',
                       (call_id, fingerprint, reserve, 'reserved'))
        return call_id, input_upper

    def _unknown(self, call_id, started, failure_code, continuation_safe):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE study_calls SET state='unknown',elapsed_seconds=?,failure_code=?,continuation_safe=? WHERE id=?",
                       (time.monotonic()-started, failure_code, int(continuation_safe), call_id))

    def complete_result(self, messages):
        call_id, input_upper = self._reserve(messages)
        started = time.monotonic()
        failure_code = 'ADAPTER_EXCEPTION'
        continuation_safe = self.continue_after_unknown
        try:
            value, tokens, meta = self.adapter.complete_result(messages)
            input_tokens = meta.get('input_tokens') if isinstance(meta, dict) else None
            output_tokens = meta.get('output_tokens') if isinstance(meta, dict) else None
            if ((type(tokens) is int and tokens > input_upper + 3000)
                    or (type(input_tokens) is int and input_tokens > input_upper)
                    or (type(output_tokens) is int and output_tokens > 3000)):
                continuation_safe = False
                failure_code = 'USAGE_BOUND_EXCEEDED'
            else:
                failure_code = 'USAGE_INVALID'
            valid = (type(tokens) is int and type(input_tokens) is int and type(output_tokens) is int
                     and 0 <= input_tokens <= input_upper and 0 <= output_tokens <= 3000
                     and tokens == input_tokens + output_tokens)
            if not valid:
                raise DomainError('STUDY_BUDGET_UNKNOWN', '模型用量报告无效，保留预留并停止后续付费调用')
            response = json.dumps(value, ensure_ascii=False)
            request_id = meta.get('request_id')
            if request_id is not None and not isinstance(request_id, str):
                request_id = None
            with self._connect() as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute("""UPDATE study_calls SET state='settled',charged_upper_micro=?,
                    input_tokens=?,output_tokens=?,request_id=?,response_json=?,elapsed_seconds=? WHERE id=?""",
                    (2*input_tokens + 8*output_tokens, input_tokens, output_tokens, request_id,
                     response, time.monotonic()-started, call_id))
            return value, tokens, meta
        except BaseException as error:
            if failure_code == 'ADAPTER_EXCEPTION' and isinstance(error, DomainError):
                failure_code = error.code if error.code in {'PROVIDER_ERROR', 'MODEL_OUTPUT_INVALID', 'KEY_REQUIRED'} else 'ADAPTER_EXCEPTION'
            self._unknown(call_id, started, failure_code, continuation_safe)
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            # Never retain the provider's exception text, which could contain secrets.
            message = ('调用未能确认费用，按请求上限保留预留；可继续不同的新请求，禁止重发本请求'
                       if continuation_safe else '调用未能确认费用，保留预留并停止后续付费调用；未自动重试')
            raise DomainError('STUDY_BUDGET_UNKNOWN', message) from None

    def summary(self):
        with self._connect() as db:
            row = db.execute("""SELECT COUNT(*),
                COALESCE(SUM(CASE WHEN state='settled' THEN charged_upper_micro ELSE 0 END),0),
                COALESCE(SUM(CASE WHEN state!='settled' THEN reserved_micro ELSE 0 END),0),
                COALESCE(SUM(CASE WHEN state!='settled' THEN 1 ELSE 0 END),0)
                FROM study_calls""").fetchone()
        calls, charged, reserved, unknown = row
        return {'cap_cny': self.cap_micro / 1_000_000,
                'charged_upper_cny': charged / 1_000_000,
                'reserved_unknown_cny': reserved / 1_000_000,
                'committed_upper_cny': (charged + reserved) / 1_000_000,
                'calls': calls, 'unknown_calls': unknown}

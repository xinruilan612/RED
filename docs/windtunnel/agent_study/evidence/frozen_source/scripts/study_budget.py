"""Separate, fail-closed CNY budget for authorized study calls through Calls.

Peak DeepSeek rates: input 2 and output 8 microCNY/token. This adapter
assumes the project's non-thinking provider enforces max_tokens=3000.
The ledger is never a production testing_budget setting.
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
    def __init__(self, adapter, ledger_path, cap_cny=5):
        try:
            micro = Decimal(str(cap_cny)) * 1_000_000
            if not micro.is_finite() or micro != micro.to_integral_value() or not 0 < micro <= 5_000_000:
                raise ValueError
            self.cap_micro = int(micro)
        except (ValueError, InvalidOperation, TypeError):
            raise DomainError('STUDY_BUDGET_INVALID', '测试预算须为不超过5元的正数，精度不超过百万分之一元') from None
        self.adapter = adapter
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
            existing = db.execute('SELECT cap_micro FROM study_budget WHERE id=1').fetchone()
            if existing is None:
                db.execute('INSERT INTO study_budget VALUES (1,?)', (self.cap_micro,))
            elif existing[0] != self.cap_micro:
                raise DomainError('STUDY_BUDGET_INVALID', '已有账本预算不可重置或修改')

    def _connect(self):
        return sqlite3.connect(str(self.ledger_path), timeout=30)

    def _reserve(self, messages):
        encoded = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        input_upper = sum(len(m['content'].encode('utf-8')) for m in messages) + 1024
        reserve = input_upper * 2 + 3000 * 8
        call_id = str(uuid4())
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            # One paid request at a time, including across processes. A crash
            # leaves reserved state, which must never enable an automatic retry.
            if db.execute("SELECT 1 FROM study_calls WHERE state!='settled' LIMIT 1").fetchone():
                raise DomainError('STUDY_BUDGET_UNKNOWN', '已有调用在途或用量未知，已停止后续付费调用')
            used = db.execute('SELECT COALESCE(SUM(COALESCE(charged_upper_micro,reserved_micro)),0) FROM study_calls').fetchone()[0]
            if used + reserve > self.cap_micro:
                raise DomainError('STUDY_BUDGET_EXCEEDED', '本次保守预留将超过测试总额上限，未发起调用')
            db.execute('INSERT INTO study_calls(id,messages_sha256,reserved_micro,state) VALUES(?,?,?,?)',
                       (call_id, hashlib.sha256(encoded).hexdigest(), reserve, 'reserved'))
        return call_id, input_upper

    def _unknown(self, call_id, started):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE study_calls SET state='unknown',elapsed_seconds=? WHERE id=?", (time.monotonic()-started, call_id))

    def complete_result(self, messages):
        call_id, input_upper = self._reserve(messages)
        started = time.monotonic()
        try:
            value, tokens, meta = self.adapter.complete_result(messages)
            input_tokens = meta.get('input_tokens') if isinstance(meta, dict) else None
            output_tokens = meta.get('output_tokens') if isinstance(meta, dict) else None
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
            self._unknown(call_id, started)
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            # Never retain the provider's exception text, which could contain secrets.
            raise DomainError('STUDY_BUDGET_UNKNOWN', '调用未能确认费用，保留预留并停止后续付费调用；未自动重试') from None

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

"""Transactional local repository for domain tests; production PostgreSQL pending."""
import json
import sqlite3
from dataclasses import asdict
from contextlib import contextmanager

from backend.contracts import PARAMETERS, require, integer
from backend.workflow import Run, digest


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS commands (
                    run_id TEXT NOT NULL, key TEXT NOT NULL, hash TEXT NOT NULL, response TEXT NOT NULL,
                    PRIMARY KEY(run_id,key));
                CREATE TABLE IF NOT EXISTS reservations (
                    run_id TEXT NOT NULL, call_id TEXT NOT NULL, tokens INTEGER NOT NULL,
                    actual INTEGER, PRIMARY KEY(run_id,call_id));
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _get(db, run_id, owner):
        row = db.execute('SELECT payload FROM runs WHERE id=? AND owner=?', (run_id,owner)).fetchone()
        require(row is not None, 'RESOURCE_NOT_FOUND', '任务不可访问')
        return Run(**json.loads(row[0]))

    def create(self, owner, snapshot, context=None):
        require(isinstance(owner,str) and owner and isinstance(snapshot,str) and snapshot,
                'INVALID_INPUT', '身份和快照不能为空')
        run = Run(owner_id=owner, snapshot_id=snapshot, context=context or {})
        run.event('run.queued')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            active = db.execute('SELECT payload FROM runs WHERE owner=?', (owner,)).fetchall()
            require(not any(json.loads(row[0])['run_status'] not in ('SUCCEEDED','FAILED','CANCELLED','EXPIRED') for row in active),
                    'RUN_ALREADY_ACTIVE', '已有活跃任务')
            db.execute('INSERT INTO runs VALUES(?,?,?)', (run.run_id,owner,json.dumps(asdict(run))))
        return run

    def get(self, run_id, owner):
        with self.connect() as db:
            return self._get(db, run_id, owner)

    def command(self, run_id, owner, expected_version, key, action, payload=None):
        """Internal service entry; public adapters must expose a smaller action whitelist."""
        payload = {} if payload is None else payload
        require(isinstance(payload,dict) and isinstance(key,str) and key, 'INVALID_INPUT', '命令参数无效')
        integer(expected_version, 'expected_version')
        actions = ('start','cancel','branch','retry','join','supplement','draft','reviewed','accept','edit','demo_step','demo_supplement')
        require(action in actions, 'INVALID_INPUT', '未知命令')
        fingerprint = digest({'version':expected_version,'action':action,'payload':payload})
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run = self._get(db, run_id, owner)
            prior = db.execute('SELECT hash,response FROM commands WHERE run_id=? AND key=?', (run_id,key)).fetchone()
            if prior:
                require(prior[0] == fingerprint, 'IDEMPOTENCY_CONFLICT', '幂等键已用于其他命令')
                return Run(**json.loads(prior[1]))
            require(run.status_version == expected_version, 'VERSION_CONFLICT', '任务已更新')
            getattr(run, action)(**payload)
            run.status_version += 1
            encoded = json.dumps(asdict(run), ensure_ascii=False)
            db.execute('UPDATE runs SET payload=? WHERE id=?', (encoded,run_id))
            db.execute('INSERT INTO commands VALUES(?,?,?,?)', (run_id,key,fingerprint,encoded))
            return run

    def reserve(self, run_id, owner, call_id, tokens):
        """Atomic worst-case token reservation. No paid provider is enabled here."""
        integer(tokens, 'tokens', 1)
        require(isinstance(call_id,str) and call_id, 'INVALID_INPUT', '调用 ID 无效')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run = self._get(db,run_id,owner)
            old = db.execute('SELECT tokens FROM reservations WHERE run_id=? AND call_id=?', (run_id,call_id)).fetchone()
            if old:
                require(old[0] == tokens, 'IDEMPOTENCY_CONFLICT', '同一调用不能改额度')
                return
            require(run.run_status == 'RUNNING', 'INVALID_TRANSITION', '当前不能调用模型')
            count, used = db.execute('SELECT COUNT(*), COALESCE(SUM(COALESCE(actual,tokens)),0) FROM reservations WHERE run_id=?', (run_id,)).fetchone()
            require(count < PARAMETERS['run_attempts_max'] and used + tokens <= PARAMETERS['run_tokens_max'],
                    'BUDGET_EXCEEDED', '调用或 Token 预算不足')
            db.execute('INSERT INTO reservations VALUES(?,?,?,NULL)', (run_id,call_id,tokens))

    def settle(self, run_id, owner, call_id, actual):
        # Unknown consumption remains reserved; no fictitious zero usage.
        if actual is not None:
            integer(actual, 'actual')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._get(db,run_id,owner)
            row = db.execute('SELECT tokens,actual FROM reservations WHERE run_id=? AND call_id=?', (run_id,call_id)).fetchone()
            require(row is not None, 'INVALID_INPUT', '调用未预留')
            if actual is None:
                return
            require(actual <= row[0], 'USAGE_OVER_RESERVATION', '实际用量超过预留，需人工核对')
            require(row[1] is None or row[1] == actual, 'IDEMPOTENCY_CONFLICT', '用量已结算')
            db.execute('UPDATE reservations SET actual=? WHERE run_id=? AND call_id=?', (actual,run_id,call_id))

    def list_runs(self, owner):
        with self.connect() as db:
            rows = db.execute('SELECT payload FROM runs WHERE owner=? ORDER BY rowid DESC LIMIT 50', (owner,)).fetchall()
            return [Run(**json.loads(row[0])) for row in rows]

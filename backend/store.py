"""Transactional domain repository for PostgreSQL and offline SQLite compatibility."""
import json
from dataclasses import asdict
from uuid import uuid4
from backend.database import connect

from backend.contracts import PARAMETERS, require, integer
from backend.workflow import Run, digest


class Store:
    def __init__(self, path):
        self.path = str(path)
        self.postgres = self.path.startswith(('postgresql://', 'postgres://'))
        self.order_column = 'created_seq' if self.postgres else 'rowid'
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
                CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS social_accounts (
                    owner TEXT NOT NULL, id TEXT NOT NULL, platform TEXT NOT NULL,
                    name TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(owner,id));
                CREATE TABLE IF NOT EXISTS account_records (
                    owner TEXT NOT NULL, account_id TEXT NOT NULL, kind TEXT NOT NULL,
                    id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(owner,kind,id),
                    FOREIGN KEY(owner,account_id) REFERENCES social_accounts(owner,id));
                CREATE INDEX IF NOT EXISTS account_record_lookup ON account_records(owner,account_id,kind);
            ''')
            if self.postgres:
                db.execute('ALTER TABLE runs ADD COLUMN IF NOT EXISTS created_seq BIGSERIAL')
            db.execute("INSERT INTO schema_migrations VALUES(1,?) ON CONFLICT(version) DO NOTHING", ('2026-09-21',))

    def connect(self):
        return connect(self.path)

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
            db.execute('INSERT INTO runs(id,owner,payload) VALUES(?,?,?)', (run.run_id,owner,json.dumps(asdict(run))))
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
            job = db.execute('SELECT status FROM runtime_jobs WHERE run_id=?',(run_id,)).fetchone() if db.has_table('runtime_jobs') else None
            if job and action!='cancel':
                require(job[0] not in ('queued','running','pausing'),'JOB_ACTIVE','后台任务尚未停稳，请稍后重试')
            before = run.drafts[-1] if action == 'edit' else None
            getattr(run, action)(**payload)
            if before is not None:
                from backend.accounts import capture_edit
                capture_edit(db, run, before)
            if job and action in ('accept','cancel'):
                db.execute("UPDATE runtime_jobs SET status='done',token=NULL WHERE run_id=?",(run_id,))
            elif job and job[0] in ('paused','blocked') and action in ('edit','demo_supplement'):
                db.execute('UPDATE runtime_jobs SET thread_id=? WHERE run_id=?',(str(uuid4()),run_id))
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
            rows = db.execute(f'SELECT payload FROM runs WHERE owner=? ORDER BY {self.order_column} DESC LIMIT 50', (owner,)).fetchall()
            return [Run(**json.loads(row[0])) for row in rows]

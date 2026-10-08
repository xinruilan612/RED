"""Forward-only, transactional core migrations, separate from legacy bootstrap DDL.

Never rewrite a shipped migration. A checksum mismatch fails startup rather than
silently interpreting existing data with a different schema.
"""
import hashlib
from backend.contracts import require

MIGRATIONS = ((1, '''
CREATE TABLE IF NOT EXISTS runtime_jobs (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE REFERENCES runs(id),
 owner TEXT NOT NULL, status TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 0,
 lease_until DOUBLE PRECISION, token TEXT, error TEXT, updated DOUBLE PRECISION NOT NULL,
 thread_id TEXT NOT NULL, policy TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS runtime_jobs_ready ON runtime_jobs(status,lease_until);
CREATE TABLE IF NOT EXISTS runtime_nodes (
 run_id TEXT NOT NULL REFERENCES runs(id), node_key TEXT NOT NULL,
 stage TEXT NOT NULL, input_hash TEXT NOT NULL, output TEXT NOT NULL,
 created DOUBLE PRECISION NOT NULL, PRIMARY KEY(run_id,node_key));
CREATE TABLE IF NOT EXISTS model_audit (
 call_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, agent TEXT NOT NULL,
 stage TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
 route_version TEXT NOT NULL, prompt_version TEXT NOT NULL,
 input_hash TEXT NOT NULL, sources TEXT NOT NULL, snapshot_id TEXT NOT NULL,
 started DOUBLE PRECISION NOT NULL, duration_ms INTEGER,
 request_id TEXT, input_tokens INTEGER, output_tokens INTEGER,
 rate DOUBLE PRECISION NOT NULL, outcome TEXT NOT NULL);
'''), (2, '''
CREATE TABLE IF NOT EXISTS runtime_commands (
 run_id TEXT NOT NULL REFERENCES runs(id), key TEXT NOT NULL,
 fingerprint TEXT NOT NULL, PRIMARY KEY(run_id,key));
CREATE TABLE IF NOT EXISTS runtime_workers (
 id TEXT PRIMARY KEY, heartbeat DOUBLE PRECISION NOT NULL);
ALTER TABLE runtime_jobs ADD COLUMN elapsed DOUBLE PRECISION NOT NULL DEFAULT 0;
'''), (3, '''
CREATE TABLE windtunnel_checklists (
 id TEXT NOT NULL, owner TEXT NOT NULL, account_id TEXT NOT NULL,
 version INTEGER NOT NULL, title TEXT NOT NULL, payload TEXT NOT NULL,
 created_at DOUBLE PRECISION NOT NULL, PRIMARY KEY(id,version));
CREATE INDEX windtunnel_checklists_scope ON windtunnel_checklists(owner,account_id);
CREATE TABLE windtunnel_checklist_commands (
 owner TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL,
 response TEXT NOT NULL, PRIMARY KEY(owner,key));
'''), (4, '''
CREATE TABLE operations_plan_attempts (
 owner TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL,
 account_id TEXT NOT NULL, week_start TEXT NOT NULL,
 status TEXT NOT NULL, response TEXT, error TEXT,
 created_at DOUBLE PRECISION NOT NULL,
 PRIMARY KEY(owner,key));
CREATE UNIQUE INDEX operations_plan_one_active_week ON operations_plan_attempts(owner,account_id,week_start) WHERE status='running';
'''), (5, '''
CREATE TABLE testing_budgets (
 owner TEXT PRIMARY KEY, cap_micro INTEGER NOT NULL, max_runs INTEGER NOT NULL,
 created_at DOUBLE PRECISION NOT NULL);
CREATE TABLE testing_budget_roots (
 owner TEXT NOT NULL REFERENCES testing_budgets(owner), root TEXT NOT NULL,
 PRIMARY KEY(owner,root));
CREATE TABLE testing_budget_reservations (
 call_id TEXT PRIMARY KEY, reserved_micro INTEGER NOT NULL);
'''), (6, '''
CREATE TABLE analytics_review_attempts (
 owner TEXT NOT NULL, analysis_id TEXT NOT NULL, run_id TEXT NOT NULL,
 snapshot_hash TEXT NOT NULL, status TEXT NOT NULL, response TEXT, error TEXT,
 created_at DOUBLE PRECISION NOT NULL, PRIMARY KEY(owner,analysis_id));
'''), (7, '''
CREATE TABLE run_visibility (
 run_id TEXT PRIMARY KEY REFERENCES runs(id), owner TEXT NOT NULL,
 deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0,1)),
 changed_at DOUBLE PRECISION NOT NULL);
CREATE INDEX run_visibility_owner ON run_visibility(owner,deleted);
'''), (8, '''
CREATE TABLE testing_budget_limits (
 owner TEXT PRIMARY KEY REFERENCES testing_budgets(owner));
'''))


def upgrade(store, migrations=None):
    migrations = MIGRATIONS if migrations is None else migrations
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS core_migrations (version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        applied = dict(db.execute('SELECT version,checksum FROM core_migrations').fetchall())
        require(set(applied) <= {v for v, _ in migrations}, 'SCHEMA_TOO_NEW', '数据库版本高于当前程序；请使用匹配版本')
        for version, sql in migrations:
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            if version in applied:
                require(applied[version] == checksum, 'MIGRATION_CHANGED', '已应用迁移被修改；停止启动')
                continue
            db.executescript(sql)
            db.execute('INSERT INTO core_migrations(version,checksum) VALUES(?,?)', (version, checksum))

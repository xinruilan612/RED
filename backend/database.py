"""Small DB-API boundary; SQLite remains an offline compatibility backend.

PostgreSQL serializes short domain writes with a transaction advisory lock. No
network/model call is made under that lock. This deliberately favors correctness
over write throughput for the initial private beta.
"""
import sqlite3
from contextlib import contextmanager


class Connection:
    def __init__(self, raw, postgres=False):
        self.raw, self.postgres = raw, postgres

    def execute(self, sql, params=()):
        if self.postgres:
            if sql == 'BEGIN IMMEDIATE':
                return self.raw.execute('SELECT pg_advisory_xact_lock(748215901)')
            sql = sql.replace('?', '%s').replace("date(created)=date('now')", 'CAST(created AS date)=CURRENT_DATE')
        return self.raw.execute(sql, params)

    def executescript(self, sql):
        # Only repository-owned DDL, never user input. Preserve transaction scope.
        for statement in sql.split(';'):
            if statement.strip():
                self.execute(statement)

    def columns(self, table):
        if self.postgres:
            return [r[0] for r in self.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=? ORDER BY ordinal_position', (table,))]
        return [r[1] for r in self.execute('PRAGMA table_info(' + table + ')')]

    def has_table(self, table):
        if self.postgres:
            return bool(self.execute('SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=?', (table,)).fetchone())
        return bool(self.execute('SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=?', (table,)).fetchone())


@contextmanager
def connect(target):
    postgres = target.startswith(('postgresql://', 'postgres://'))
    if postgres:
        import psycopg
        raw = psycopg.connect(target, connect_timeout=10)
        raw.execute("SET lock_timeout = '10s'")
        raw.execute("SET statement_timeout = '30s'")
    else:
        raw = sqlite3.connect(target, timeout=10)
        raw.execute('PRAGMA foreign_keys=ON')
    try:
        yield Connection(raw, postgres)
        raw.commit()
    except BaseException:
        raw.rollback()
        raise
    finally:
        raw.close()


def project_operations(db, owner, state):
    """Indexed relational directory alongside the versioned workflow aggregate."""
    import json
    for a in state['accounts']:
        db.execute('INSERT INTO social_accounts(owner,id,platform,name,revision,payload) VALUES(?,?,?,?,?,?) ON CONFLICT(owner,id) DO UPDATE SET name=excluded.name,revision=excluded.revision,payload=excluded.payload',
                   (owner,a['id'],a['platform'],a['name'],a['revision'],json.dumps(a,ensure_ascii=False)))
    for kind in ('publications','metrics','memories','preferences','analyses','plans','competitors','experiments',
                 'services','portfolio_items','promotion_briefs','inquiries','promotion_analyses',
                 'signals','hypotheses'):
        for r in state.get(kind, []):
            identity = r.get('account_id')
            if identity:
                db.execute('INSERT INTO account_records(owner,account_id,kind,id,payload) VALUES(?,?,?,?,?) ON CONFLICT(owner,kind,id) DO UPDATE SET account_id=excluded.account_id,payload=excluded.payload',
                           (owner,identity,kind,r['id'],json.dumps(r,ensure_ascii=False)))

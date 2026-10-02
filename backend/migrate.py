"""Copy a SQLite snapshot into an empty project PostgreSQL database, atomically.

Never deletes a source or overwrites a divergent target. Repeated imports of the
same snapshot verify every row. Secrets/cookies are not printed in reports.
"""
import argparse
from contextlib import closing
import hashlib
import json
import sqlite3
from pathlib import Path
from backend.store import Store
from backend.execution import Executor
from backend.operations import Operations
from backend.provider import Config
from backend.accounts import migrate
from backend.database import project_operations
from backend.contracts import require

TABLES = ('runs','commands','reservations','operations','operations_commands','demo_sessions','recovery_keys',
          'live_steps','live_calls','live_lineage','live_recoveries')


def copy_database(source, target):
    store=Store(target); Operations(store); Executor(store,Config())
    with store.connect() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS demo_sessions(token_hash TEXT PRIMARY KEY,owner TEXT NOT NULL,csrf TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS recovery_keys(owner TEXT PRIMARY KEY,key_hash TEXT UNIQUE NOT NULL);
            CREATE TABLE IF NOT EXISTS import_batches(source_hash TEXT PRIMARY KEY,report TEXT NOT NULL);''')
    counts={}; records=[]
    # sqlite3's transaction context commits/rolls back but does not close the
    # handle; closing owns it on every path, including read/target failures.
    with closing(sqlite3.connect('file:'+str(Path(source).resolve())+'?mode=ro',uri=True)) as src, src:
        src.execute('BEGIN')
        available={r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in TABLES:
            if table not in available: continue
            columns=[r[1] for r in src.execute('PRAGMA table_info('+table+')')]
            rows=src.execute('SELECT '+','.join(columns)+' FROM '+table+' ORDER BY rowid').fetchall()
            counts[table]=len(rows);records.append((table,columns,rows))
    fingerprint=hashlib.sha256(json.dumps(records,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        previous=db.execute('SELECT report FROM import_batches WHERE source_hash=?',(fingerprint,)).fetchone()
        if not previous:
            require(not any(db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in TABLES if db.has_table(t)), 'MIGRATION_CONFLICT','目标含业务记录；请使用空数据库，不能覆盖已有数据')
        for table,columns,rows in records:
            if not previous:
                sql='INSERT INTO '+table+'('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')'
                for row in rows: db.execute(sql,row)
            target_rows=db.execute('SELECT '+','.join(columns)+' FROM '+table).fetchall()
            canonical=lambda r: json.dumps(list(r),ensure_ascii=False)
            require(sorted(map(canonical,rows))==sorted(map(canonical,target_rows)), 'MIGRATION_CONFLICT','迁移校验失败或目标已变化：'+table)
        for owner,payload in db.execute('SELECT owner,payload FROM operations').fetchall():
            project_operations(db,owner,migrate(json.loads(payload),owner))
        report={'source_hash':fingerprint,'counts':counts,'verified':True}
        if not previous: db.execute('INSERT INTO import_batches VALUES(?,?)',(fingerprint,json.dumps(report)))
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',required=True)
    parser.add_argument('--target',default=None)
    args=parser.parse_args()
    from backend.api import settings
    target=args.target or settings().get('DATABASE_URL')
    require(bool(target),'CONFIG_INVALID','请配置 DATABASE_URL')
    print(json.dumps(copy_database(args.source,target),ensure_ascii=False,indent=2))


if __name__=='__main__': main()

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
            db.execute('BEGIN IMMEDIATE')
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
            require(not any(json.loads(row[0]).get('workflow_type','creation') == run.workflow_type and json.loads(row[0])['run_status'] not in ('SUCCEEDED','FAILED','CANCELLED','EXPIRED') for row in active),
                    'RUN_ALREADY_ACTIVE', '已有活跃任务')
            from backend.comment_feedback import assert_visible
            assert_visible(run,db)
            db.execute('INSERT INTO runs(id,owner,payload) VALUES(?,?,?)', (run.run_id,owner,json.dumps(asdict(run))))
        return run

    def get(self, run_id, owner):
        with self.connect() as db:
            return self._get(db, run_id, owner)

    def command(self, run_id, owner, expected_version, key, action, payload=None, *, revision_retrieval=None):
        """Internal service entry; public adapters must expose a smaller action whitelist."""
        payload = {} if payload is None else payload
        require(isinstance(payload,dict) and isinstance(key,str) and key, 'INVALID_INPUT', '命令参数无效')
        integer(expected_version, 'expected_version')
        actions = ('start','cancel','branch','retry','join','supplement','draft','reviewed','accept','adopt_manual','edit','retitle','review_current','request_revision','demo_step','demo_supplement','skip_questions')
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
            if action in ('accept','adopt_manual','edit','request_revision') and db.has_table('live_steps'):
                require(not db.execute("SELECT 1 FROM live_steps WHERE run_id=? AND state='running'",(run_id,)).fetchone(), 'JOB_ACTIVE', '模型正在执行，请等待完成')
            before = run.drafts[-1] if action == 'edit' and run.drafts else None
            arguments=dict(payload)
            if action=='request_revision' and 'document_ids' in arguments:
                ids=arguments.pop('document_ids')
                require(revision_retrieval is not None,'INVALID_INPUT','改稿资料须由服务端检索')
                account=run.context.get('operations',{}).get('account_id')
                from backend.knowledge import document_is_public
                facts=revision_retrieval['groups']['facts']
                require(set(ids)=={s['document_id'] for s in facts},'INVALID_INPUT','改稿资料不完整')
                for source in facts:
                    row=db.execute("SELECT d.version,v.metadata,d.source_url FROM knowledge_documents d JOIN knowledge_versions v ON v.document_id=d.id AND v.version=d.version WHERE d.id=? AND d.owner=? AND d.account_id=? AND d.status='active'",
                                   (source['document_id'],owner,account)).fetchone()
                    require(row is not None and row[0]==source['version'] and
                            document_is_public(db,owner,account,json.loads(row[1]),row[2]),
                            'SOURCE_VISIBILITY_CHANGED','改稿资料已更新或不可访问，请重新选择')
            getattr(run, action)(**arguments)
            if action == 'demo_step':
                from backend.creation_algorithms import refresh
                refresh(run)
            if action=='request_revision' and revision_retrieval is not None:
                from copy import deepcopy
                old=deepcopy(run.context.get('creation_retrieval',{}))
                run.context.setdefault('revision_source_history',[]).append({
                    'snapshot_id':run.snapshot_id,'retrieval':old,'evidence':deepcopy(run.context.get('evidence',[]))})
                fresh=deepcopy(revision_retrieval)
                for group in ('methods','examples'):
                    fresh['groups'][group]=old.get('groups',{}).get(group,[])
                    fresh['filters'][group]=old.get('filters',{}).get(group,fresh['filters'][group])
                fresh['sources']=[s for group in fresh['groups'].values() for s in group]
                fresh['context_chars']=sum(len(s['text']) for s in fresh['sources'])
                require(fresh['context_chars']<=fresh['limits']['total_chars'],
                        'INVALID_INPUT','改稿资料与原参考超过输入限额，请减少资料')
                run.snapshot_id=digest({'previous':run.snapshot_id,'revision':run.context['pending_revision']['id'],
                                       'sources':fresh['sources']})
                run.context['creation_retrieval']=fresh
                run.context['retrieval']=fresh
                run.context['evidence']=fresh['sources']
                run.context['knowledge_selection']={**run.context.get('knowledge_selection',{}),
                    'enabled':True,'document_ids':payload['document_ids']}
                run.context['pending_revision']['snapshot_id']=run.snapshot_id
                run.context['revision_requests'][-1]['snapshot_id']=run.snapshot_id
                run.event('artifact.created',stage='revision_sources',snapshot_id=run.snapshot_id)
                # Derived plans may not be presented as current after new evidence.
                run.context.pop('algorithm_state', None)
            if before is not None:
                from backend.accounts import capture_edit
                capture_edit(db, run, before)
            if job and action in ('accept','adopt_manual','cancel'):
                db.execute("UPDATE runtime_jobs SET status='done',token=NULL WHERE run_id=?",(run_id,))
            elif job and action in ('edit','demo_supplement','request_revision'):
                db.execute('UPDATE runtime_jobs SET thread_id=? WHERE run_id=?',(str(uuid4()),run_id))
            run.status_version += 1
            encoded = json.dumps(asdict(run), ensure_ascii=False)
            db.execute('UPDATE runs SET payload=? WHERE id=?', (encoded,run_id))
            db.execute('INSERT INTO commands VALUES(?,?,?,?)', (run_id,key,fingerprint,encoded))
            return run

    def delete_run(self, run_id, owner):
        """Permanently remove a terminal run and its task-local artifacts.

        Model/cost audit rows are retained as a billing ledger; they contain
        hashes and token counts, not the draft body. Everything that can
        reopen or reconstruct the task is deleted.
        """
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run = self._get(db, run_id, owner)
            require(run.run_status not in ('QUEUED','RUNNING'), 'INVALID_TRANSITION', '请先取消正在运行的任务，再删除')
            job = db.execute('SELECT status FROM runtime_jobs WHERE run_id=?', (run_id,)).fetchone() if db.has_table('runtime_jobs') else None
            require(not job or job[0] not in ('queued','running','pausing'), 'JOB_ACTIVE', '后台任务尚未停稳，请稍后再删除')
            for table, column in (('runtime_jobs','run_id'),('runtime_nodes','run_id'),('runtime_commands','run_id'),
                                  ('live_calls','run_id'),('live_steps','run_id'),('commands','run_id'),
                                  ('reservations','run_id'),('live_lineage','run_id')):
                db.execute(f'DELETE FROM {table} WHERE {column}=?', (run_id,))
            db.execute('DELETE FROM live_recoveries WHERE parent=? OR child=?', (run_id, run_id))
            db.execute('DELETE FROM runs WHERE id=? AND owner=?', (run_id, owner))
            return {'run_id': run_id, 'deleted': True}

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

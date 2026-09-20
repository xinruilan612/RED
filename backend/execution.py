"""Claim before network; no provider calls inside SQLite transactions or implicit retries."""
import json
import copy
from dataclasses import asdict
from uuid import uuid4

from backend.contracts import DomainError, require
from backend.workflow import Run, digest
from backend.provider import DeepSeek, RATE
from backend.live import advance

FAMILY = "SELECT run_id FROM live_lineage WHERE budget_id=?"


class Executor:
    def __init__(self,store,config,client=None):
        self.store,self.config=store,config
        self.client=client or DeepSeek(config)
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS live_steps (
                    run_id TEXT, version INTEGER, key TEXT, fingerprint TEXT,
                    state TEXT, response TEXT, error TEXT, PRIMARY KEY(run_id,version), UNIQUE(run_id,key));
                CREATE TABLE IF NOT EXISTS live_calls (
                    id TEXT PRIMARY KEY, run_id TEXT, agent TEXT, stage TEXT,
                    reserved INTEGER, actual INTEGER, state TEXT, error TEXT,
                    created TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS live_lineage (run_id TEXT PRIMARY KEY, budget_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS live_recoveries (parent TEXT PRIMARY KEY, child TEXT NOT NULL);
            ''')
            columns={r[1] for r in db.execute('PRAGMA table_info(live_calls)')}
            if 'response_json' not in columns:db.execute('ALTER TABLE live_calls ADD COLUMN response_json TEXT')
            db.execute('INSERT OR IGNORE INTO live_lineage SELECT id,id FROM runs')

    @staticmethod
    def budget_id(db,run_id):
        db.execute('INSERT OR IGNORE INTO live_lineage VALUES(?,?)',(run_id,run_id))
        return db.execute('SELECT budget_id FROM live_lineage WHERE run_id=?',(run_id,)).fetchone()[0]

    def recover(self,run_id,owner,version):
        # New continuation run, immutable failed parent; all limits shared with ancestry.
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=self.store._get(db,run_id,owner)
            previous=db.execute('SELECT child FROM live_recoveries WHERE parent=?',(run_id,)).fetchone()
            if previous:return self.store._get(db,previous[0],owner)
            require(old.status_version==version,'VERSION_CONFLICT','任务已更新')
            require(old.context.get('mode')=='live' and old.run_status=='FAILED','INVALID_TRANSITION','只能从失败的真实任务继续')
            require(not any(json.loads(row[0])['run_status'] not in ('SUCCEEDED','FAILED','CANCELLED','EXPIRED') for row in db.execute('SELECT payload FROM runs WHERE owner=?',(owner,))),
                    'RUN_ALREADY_ACTIVE','请先处理已有活跃任务')
            root=self.budget_id(db,run_id)
            require(not db.execute(f"SELECT 1 FROM live_calls WHERE run_id IN ({FAMILY}) AND actual IS NULL",(root,)).fetchone(),
                    'USAGE_UNKNOWN','此前调用用量不确定，停止恢复以避免重复计费')
            require(not (old.review and old.review['decision']=='revision_required' and old.iteration>=2),'STAGE_ATTEMPT_LIMIT','已用完3轮稿件，不再恢复')
            candidate=copy.deepcopy(old)
            candidate.run_id=str(uuid4());candidate.run_status='QUEUED';candidate.wait_reason=None;candidate.status_version=0
            candidate.events=[];candidate.context['resume_from']=old.run_id
            candidate.event('run.queued',resume_from=old.run_id)
            db.execute('INSERT INTO runs VALUES(?,?,?)',(candidate.run_id,owner,json.dumps(asdict(candidate),ensure_ascii=False)))
            db.execute('INSERT INTO live_lineage VALUES(?,?)',(candidate.run_id,root))
            db.execute('INSERT INTO live_recoveries VALUES(?,?)',(old.run_id,candidate.run_id))
            return candidate

    def public(self,run):
        with self.store.connect() as db:
            root=self.budget_id(db,run.run_id)
            calls=db.execute(f'SELECT id,agent,stage,reserved,actual,state,error,response_json,run_id FROM live_calls WHERE run_id IN ({FAMILY}) ORDER BY rowid',(root,)).fetchall()
            pending=db.execute("SELECT COUNT(*) FROM live_steps WHERE run_id=? AND state='running'",(run.run_id,)).fetchone()[0]
        items=[]
        for c in calls:
            item=dict(zip(('id','agent','stage','reserved_tokens','tokens','status','error'),c[:7]))
            item['inherited']=c[8]!=run.run_id
            if c[5]=='invalid' and c[7]:item['diagnostic_response']=json.loads(c[7])
            items.append(item)
        return {'in_flight':bool(pending) and run.run_status not in ('CANCELLED','FAILED'),'calls':items,
                'usage':{'model_calls':len(items),'tokens':sum(c['tokens'] or 0 for c in items),
                         'unknown_calls':sum(c['tokens'] is None for c in items),
                         'cost':None,'cost_upper_estimate_usd':round(sum(c['tokens'] if c['tokens'] is not None else c['reserved_tokens'] for c in items)*RATE,6),
                         'currency':'USD'}}

    def step(self,run_id,owner,version,key):
        require(self.config.ready,'KEY_REQUIRED','请填写 .env 的 DEEPSEEK_API_KEY，然后重启服务')
        fingerprint=digest({'version':version,'action':'next'})
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run=self.store._get(db,run_id,owner)
            root=self.budget_id(db,run_id)
            prior=db.execute('SELECT fingerprint,state,response,error FROM live_steps WHERE run_id=? AND key=?',(run_id,key)).fetchone()
            if prior:
                require(prior[0]==fingerprint,'IDEMPOTENCY_CONFLICT','命令标识已用于其他操作')
                if prior[1]=='done':return Run(**json.loads(prior[2]))
                raise DomainError('STEP_ALREADY_ATTEMPTED',prior[3] or '当前步骤仍在执行或上次被中断；不会重复请求，请刷新查看，必要时取消后新建')
            require(run.status_version==version,'VERSION_CONFLICT','任务已更新，请刷新')
            require(not db.execute("SELECT 1 FROM live_steps WHERE run_id=? AND state='running'",(run_id,)).fetchone(),
                    'STEP_ALREADY_ATTEMPTED','当前步骤尚未完成；刷新查看，服务重启后的未决调用请取消任务后新建')
            require(run.run_status in ('QUEUED','RUNNING'),'INVALID_TRANSITION','请先处理人工操作')
            if run.run_status=='QUEUED':run.start()
            agents=('audience','research') if run.current_stage=='brief' else (run.current_stage,)
            for agent in agents:run.event('agent.started',agent=agent,mode='live')
            run.status_version+=1
            db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(asdict(run)),run_id))
            db.execute('INSERT INTO live_steps VALUES(?,?,?,?,?,?,?)',(run_id,version,key,fingerprint,'running',None,None))
        claimed_version=run.status_version
        def call(agent,stage,messages):
            # UTF-8 byte upper bound + framing allowance; settlement uses reported usage.
            reserve=sum(len(m['content'].encode()) for m in messages)+3000+256
            call_id=str(uuid4())
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                current=self.store._get(db,run_id,owner)
                require(current.status_version==claimed_version and current.run_status=='RUNNING','VERSION_CONFLICT','任务已取消或更新，已停止后续调用')
                # Cumulative per-run cap: new snapshots/manual edits do not reset attempts.
                # Initial body and revisions are one output group, never three retries each.
                if agent=='content' and stage in ('body','revise'):
                    stage_count=db.execute(f"SELECT COUNT(*) FROM live_calls WHERE run_id IN ({FAMILY}) AND agent='content' AND stage IN ('body','revise')",(root,)).fetchone()[0]
                else:
                    stage_count=db.execute(f'SELECT COUNT(*) FROM live_calls WHERE run_id IN ({FAMILY}) AND agent=? AND stage=?',(root,agent,stage)).fetchone()[0]
                require(stage_count<3,'STAGE_ATTEMPT_LIMIT','同一步已达到3次调用上限（含首次）；任务已停止，不再调用模型')
                count,used=db.execute(f'SELECT COUNT(*),COALESCE(SUM(COALESCE(actual,reserved)),0) FROM live_calls WHERE run_id IN ({FAMILY})',(root,)).fetchone()
                daily=db.execute("SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM live_calls WHERE date(created)=date('now')").fetchone()[0]
                require(count<16 and used+reserve<=40000 and (used+reserve)*RATE<=self.config.run_budget_usd and (daily+reserve)*RATE<=self.config.day_budget_usd,
                        'BUDGET_EXCEEDED','已到调用、Token 或估算费用上限，停止执行；已有记录仍保留')
                db.execute('INSERT INTO live_calls(id,run_id,agent,stage,reserved,state) VALUES(?,?,?,?,?,?)',(call_id,run_id,agent,stage,reserve,'calling'))
            try:
                value,tokens=self.client.complete(messages)
                require(type(tokens) is int and 0<=tokens<=reserve,'MODEL_OUTPUT_INVALID','用量报告异常，停止执行并保留预留')
                with self.store.connect() as db:db.execute("UPDATE live_calls SET actual=?,state='received',response_json=? WHERE id=?",(tokens,json.dumps(value,ensure_ascii=False),call_id))
                return value,tokens,call_id
            except Exception as e:
                safe=str(e) if isinstance(e,DomainError) else '模型调用失败，未自动重试'
                with self.store.connect() as db:db.execute("UPDATE live_calls SET state='failed',error=? WHERE id=?",(safe,call_id))
                raise DomainError('PROVIDER_ERROR',safe) from None
        def validated(call_id,error):
            with self.store.connect() as db:
                db.execute('UPDATE live_calls SET state=?,error=? WHERE id=?',('invalid' if error else 'validated',error,call_id))
        failure=None
        try:advance(run,call,validated)
        except Exception as e:
            failure=str(e) if isinstance(e,DomainError) else '模型结果无法使用，已停止执行，未自动重试'
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current=self.store._get(db,run_id,owner)
            if current.status_version!=claimed_version:
                # Cancellation wins; paid usage is still retained in live_calls.
                db.execute("UPDATE live_steps SET state='discarded',error=? WHERE run_id=? AND version=?",('任务已取消或更新',run_id,version))
                return current
            if failure:
                run=current
                run._transition('FAILED')
                run.event('agent.failed',message=failure,mode='live')
            run.status_version+=1
            encoded=json.dumps(asdict(run),ensure_ascii=False)
            db.execute('UPDATE runs SET payload=? WHERE id=?',(encoded,run_id))
            db.execute('UPDATE live_steps SET state=?,response=?,error=? WHERE run_id=? AND version=?',
                       ('done',encoded,failure,run_id,version))
        return run

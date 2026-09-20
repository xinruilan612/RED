"""Claim before network; no provider calls inside SQLite transactions or implicit retries."""
import json
from dataclasses import asdict
from uuid import uuid4

from backend.contracts import DomainError, require
from backend.workflow import Run, digest
from backend.provider import DeepSeek, RATE
from backend.live import advance


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
            ''')

    def public(self,run):
        with self.store.connect() as db:
            calls=db.execute('SELECT id,agent,stage,reserved,actual,state,error FROM live_calls WHERE run_id=? ORDER BY rowid',(run.run_id,)).fetchall()
            pending=db.execute("SELECT COUNT(*) FROM live_steps WHERE run_id=? AND state='running'",(run.run_id,)).fetchone()[0]
        items=[dict(zip(('id','agent','stage','reserved_tokens','tokens','status','error'),c)) for c in calls]
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
                count,used=db.execute('SELECT COUNT(*),COALESCE(SUM(COALESCE(actual,reserved)),0) FROM live_calls WHERE run_id=?',(run_id,)).fetchone()
                daily=db.execute("SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM live_calls WHERE date(created)=date('now')").fetchone()[0]
                require(count<16 and used+reserve<=40000 and (used+reserve)*RATE<=self.config.run_budget_usd and (daily+reserve)*RATE<=self.config.day_budget_usd,
                        'BUDGET_EXCEEDED','已到调用、Token 或估算费用上限，停止执行；已有记录仍保留')
                db.execute('INSERT INTO live_calls(id,run_id,agent,stage,reserved,state) VALUES(?,?,?,?,?,?)',(call_id,run_id,agent,stage,reserve,'calling'))
            try:
                value,tokens=self.client.complete(messages)
                require(type(tokens) is int and 0<=tokens<=reserve,'MODEL_OUTPUT_INVALID','用量报告异常，停止执行并保留预留')
                with self.store.connect() as db:db.execute("UPDATE live_calls SET actual=?,state='received' WHERE id=?",(tokens,call_id))
                return value,tokens,call_id
            except Exception as e:
                safe=str(e) if isinstance(e,DomainError) else '模型调用失败，未自动重试'
                with self.store.connect() as db:db.execute("UPDATE live_calls SET state='failed',error=? WHERE id=?",(safe,call_id))
                raise DomainError('PROVIDER_ERROR',safe) from None
        failure=None
        try:advance(run,call)
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

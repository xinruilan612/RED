"""Claim before network; no provider calls inside SQLite transactions or implicit retries."""
import json
import copy
import time
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
        from backend.migrations import upgrade
        from backend.model_router import ModelRouter, Calls
        upgrade(store)
        self.router=client if isinstance(client,ModelRouter) else ModelRouter(config,client)
        from backend.model_connections import ModelConnections
        self.router.connections=ModelConnections(store,config)
        self.calls=Calls(store,config,self.router)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
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
            columns=set(db.columns('live_calls'))
            if 'response_json' not in columns:db.execute('ALTER TABLE live_calls ADD COLUMN response_json TEXT')
            if store.postgres: db.execute('ALTER TABLE live_calls ADD COLUMN IF NOT EXISTS created_seq BIGSERIAL')

    @staticmethod
    def budget_id(db,run_id):
        db.execute('INSERT INTO live_lineage VALUES(?,?) ON CONFLICT(run_id) DO NOTHING',(run_id,run_id))
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
            require(not any(json.loads(row[0]).get('workflow_type','creation') == old.workflow_type and json.loads(row[0])['run_status'] not in ('SUCCEEDED','FAILED','CANCELLED','EXPIRED') for row in db.execute('SELECT payload FROM runs WHERE owner=?',(owner,))),
                    'RUN_ALREADY_ACTIVE','请先处理已有活跃任务')
            root=self.budget_id(db,run_id)
            from backend.model_router import assert_recoverable_usage
            assert_recoverable_usage(db,root)
            require(not (old.review and old.review['decision']=='revision_required' and old.iteration>=2),'STAGE_ATTEMPT_LIMIT','已用完3轮稿件，不再恢复')
            candidate=copy.deepcopy(old)
            candidate.run_id=str(uuid4());candidate.run_status='QUEUED';candidate.wait_reason=None;candidate.status_version=0
            candidate.events=[];candidate.context['resume_from']=old.run_id
            candidate.event('run.queued',resume_from=old.run_id)
            db.execute('INSERT INTO runs(id,owner,payload) VALUES(?,?,?)',(candidate.run_id,owner,json.dumps(asdict(candidate),ensure_ascii=False)))
            db.execute('INSERT INTO live_lineage VALUES(?,?)',(candidate.run_id,root))
            db.execute('INSERT INTO live_recoveries VALUES(?,?)',(old.run_id,candidate.run_id))
            return candidate

    def public(self,run):
        with self.store.connect() as db:
            root=self.budget_id(db,run.run_id)
            calls=db.execute(f'SELECT id,agent,stage,reserved,actual,state,error,response_json,run_id FROM live_calls WHERE run_id IN ({FAMILY}) ORDER BY {self.store.order_column}',(root,)).fetchall()
            pending=db.execute("SELECT COUNT(*) FROM live_steps WHERE run_id=? AND state='running'",(run.run_id,)).fetchone()[0]
            audits={r[0]:json.loads(r[1]) for r in db.execute("SELECT call_id,sources FROM model_audit WHERE run_id IN ("+FAMILY+")",(root,))}
            metadata={r[0]:dict(zip(('provider','model','route_version','prompt_version','input_hash','snapshot_id','duration_ms','request_id','input_tokens','output_tokens','rate','billing_source','connection_id'),r[1:])) for r in db.execute("SELECT call_id,provider,model,route_version,prompt_version,input_hash,snapshot_id,duration_ms,request_id,input_tokens,output_tokens,rate,billing_source,connection_id FROM model_audit WHERE run_id IN ("+FAMILY+")",(root,))}
        items=[]
        for c in calls:
            item=dict(zip(('id','agent','stage','reserved_tokens','tokens','status','error'),c[:7]))
            item.update(metadata.get(c[0],{}));item['sources']=audits.get(c[0],[]);item['audit_legacy']=c[0] not in metadata
            item['inherited']=c[8]!=run.run_id
            if c[5]=='invalid' and c[7]:item['diagnostic_response']=json.loads(c[7])
            items.append(item)
        usage_items=[item for item in items if item['status']!='not_sent']
        policy=run.context.get('model_policy') or self.router.policy()
        return {'model_policy':policy,'in_flight':bool(pending) and run.run_status not in ('CANCELLED','FAILED'),'calls':items,
                'usage':{'model_calls':len(usage_items),'tokens':sum(c['tokens'] or 0 for c in usage_items),
                         'unknown_calls':sum(c['tokens'] is None for c in usage_items),
                         'cost':None,'cost_upper_estimate_usd':round(sum((c['tokens'] if c['tokens'] is not None else c['reserved_tokens'])*c.get('rate',RATE) for c in usage_items),6),
                         'currency':'USD'}}

    def step(self,run_id,owner,version,key):
        self.calls.config=self.config
        selected=self.store.get(run_id,owner)
        policy=selected.context.get('model_policy') or self.router.policy()
        require(self.config.ready or any(r.get('connection_id') for r in policy['routes'].values()),'KEY_REQUIRED','请配置平台或个人模型连接')
        self.router.ready(policy,owner)
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
            def guard(db):
                current=self.store._get(db,run_id,owner)
                require(current.status_version==claimed_version and current.run_status=='RUNNING','VERSION_CONFLICT','任务已取消或更新')
            return self.calls.invoke(run,agent,stage,messages,guard)
        def validated(call_id,error):
            self.calls.validated(call_id,error)
        failure=None
        review_call=None
        review_error=None
        try:
            if run.current_stage=='reviewer':
                from backend import live
                from backend.creator_context import enrich
                messages,inputs=live.messages_for(run,'review')
                started=time.monotonic()
                raw,tokens,call_id=call('reviewer','review',messages)
                review_call=(raw,tokens,call_id,inputs,round((time.monotonic()-started)*1000))
                try:output=enrich('review',live.normalize(run,'review',raw),run.context)
                except DomainError as error:
                    if error.code not in ('MODEL_OUTPUT_INVALID','REVIEW_GATE_FAILED'):
                        self.calls.validated(call_id,str(error));raise
                    review_error=error
            else:advance(run,call,validated)
        except Exception as e:
            failure=str(e) if isinstance(e,DomainError) else '模型结果无法使用，已停止执行，未自动重试'
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current=self.store._get(db,run_id,owner)
            if current.status_version!=claimed_version:
                # Cancellation wins; paid usage is still retained in live_calls.
                db.execute("UPDATE live_steps SET state='discarded',error=? WHERE run_id=? AND version=?",('任务已取消或更新',run_id,version))
                return current
            if review_call is not None and failure is None:
                from backend import live
                raw,tokens,call_id,inputs,duration=review_call
                require(current.snapshot_id==run.snapshot_id and current.drafts[-1]==run.drafts[-1]
                        and digest(current.drafts[-1]['content'])==run.drafts[-1]['content_hash'],
                        'VERSION_CONFLICT','稿件版本已变化，拒绝旧审核结果')
                run=current
                try:
                    if review_error is None:
                        try:run.reviewed(output,live.review_gates(run,output),fail_on_limit=True)
                        except DomainError as error:
                            if error.code not in ('MODEL_OUTPUT_INVALID','REVIEW_GATE_FAILED'):raise
                            review_error=error
                    if review_error is not None:
                        row=db.execute('SELECT c.response_json,c.actual,c.state,a.snapshot_id FROM live_calls c JOIN model_audit a ON a.call_id=c.id AND a.run_id=c.run_id WHERE c.id=? AND c.run_id=? AND c.stage=?',
                                       (call_id,run_id,'review')).fetchone()
                        require(row and row[0] is not None and type(row[1]) is int and row[2] in ('received','invalid','validated'),
                                'USAGE_UNKNOWN','审核响应或用量未结算，不能生成保守交接')
                        require(row[3]==run.snapshot_id and json.loads(row[0])==raw,'VERSION_CONFLICT','审核原始响应或输入快照已变化')
                        from backend.review_recovery import conservative_review
                        output=conservative_review(run,raw,review_error)
                        run.reviewed(output,live.review_gates(run,output),fail_on_limit=True)
                    self.calls.validated(call_id,str(review_error) if review_error else None,db=db)
                    log=dict(id=str(uuid4()),agent='reviewer',stage='review',mode='live',snapshot_id=run.snapshot_id,
                             input=inputs,output=output,duration_ms=duration,model_calls=1,tokens=tokens,cost=None,
                             call_id=call_id,tools=['knowledge_snapshot'] if run.context.get('evidence') else [],
                             memory='读取本任务的账号与证据快照')
                    run.node_runs.append(log)
                    run.event('agent.completed',agent='reviewer',stage='review',mode='live',node_ref=log['id'])
                except DomainError as error:
                    if error.code in ('MODEL_OUTPUT_INVALID','REVIEW_GATE_FAILED'):
                        self.calls.validated(call_id,str(error),db=db)
                    failure=str(error)
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

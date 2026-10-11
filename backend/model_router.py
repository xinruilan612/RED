"""Explicit routes and provider-independent accounting. No automatic fallback."""
import json
import time
from dataclasses import asdict, dataclass, replace
from uuid import uuid4
from backend.contracts import require, DomainError, CONTRACT, PARAMETERS
from backend.provider import DeepSeek, RATE
from backend.workflow import digest

CREATION_STAGES = ('audience','research','strategy','outline','hook','title','body','revise','review')
WINDTUNNEL_STAGES = ('wt_conditions','wt_read','wt_verify','wt_patch')
OPERATIONS_STAGES = ('operations_plan',)
STAGES = CREATION_STAGES + WINDTUNNEL_STAGES + OPERATIONS_STAGES
FAMILY = 'SELECT run_id FROM live_lineage WHERE budget_id=?'


@dataclass(frozen=True)
class Route:
    provider: str
    model: str
    rate: float = RATE
    connection_id: str | None = None
    connection_version: int | None = None
    owner_id: str | None = None
    billing_source: str = 'platform'
    run_budget_usd: float | None = None
    day_budget_usd: float | None = None


class ModelRouter:
    def __init__(self, config, client=None, routes=None, adapters=None):
        self.config = config
        self.routes = routes if routes is not None else {s:Route('deepseek',**v) for s,v in config.routes.items()}
        self.adapters = adapters or {}
        self.client = client
        self.connections = None

    def policy(self, workflow_type='creation', owner=None, connection_id=None):
        require(workflow_type in ('creation','windtunnel','operations'),'INVALID_INPUT','工作流类型无效')
        stages = {'windtunnel':WINDTUNNEL_STAGES,'operations':OPERATIONS_STAGES}.get(workflow_type,CREATION_STAGES)
        routes = {s: asdict(self.routes.get(s, Route('fixture' if self.client else 'deepseek', self.config.model))) for s in stages}
        routes={stage:{**route,'run_budget_usd':route.get('run_budget_usd') or self.config.run_budget_usd,'day_budget_usd':route.get('day_budget_usd') or self.config.day_budget_usd} for stage,route in routes.items()}
        if owner and self.connections:
            selected=self.connections.route(owner,connection_id)
            if selected:routes={stage:asdict(selected) for stage in stages}
        prompt={'windtunnel':'windtunnel.v1','operations':'operations_plan.v1'}.get(workflow_type,CONTRACT['runtime_extension']['prompt_version'])
        return {'version':digest(routes), 'routes':routes, 'prompt_version':prompt}

    def route(self, policy, stage):
        require(stage in STAGES and stage in policy.get('routes',{}) and policy.get('version') == digest(policy.get('routes')), 'CONFIG_INVALID','模型路由快照无效')
        route = Route(**policy['routes'][stage])
        require(isinstance(route.rate,(int,float)) and 0 < route.rate < 1, 'CONFIG_INVALID','模型费率上限无效')
        require(route.connection_id is not None or route.provider == 'deepseek' or self.client is not None or (route.provider,route.model) in self.adapters, 'CONFIG_INVALID','未注册的模型适配器')
        return route

    def ready(self,policy,owner):
        for stage in policy['routes']:
            route=self.route(policy,stage)
            if route.connection_id:
                require(self.connections is not None,'CONFIG_INVALID','模型连接存储未就绪')
                self.connections.adapter(route,owner)
            else:
                require(self.config.ready or self.client is not None,'KEY_REQUIRED','请配置平台 DeepSeek 或自己的模型连接')
        return True

    def complete(self, route, messages, owner=None):
        if route.connection_id:
            require(self.connections is not None,'CONFIG_INVALID','模型连接存储未就绪')
            return self.connections.adapter(route,owner).complete_result(messages)
        adapter = self.adapters.get((route.provider,route.model))
        if adapter is None:
            adapter = self.client if route.provider=='fixture' else DeepSeek(replace(self.config,model=route.model))
        require(adapter is not None,'CONFIG_INVALID','模型适配器不可用')
        if hasattr(adapter,'complete_result'):
            return adapter.complete_result(messages)
        value,tokens = adapter.complete(messages)
        return value,tokens,{}  # Not reported is unknown, never fabricated zero.


class Calls:
    def __init__(self, store, config, router):
        self.store,self.config,self.router = store,config,router

    def invoke(self, run, agent, stage, messages, guard, reuse=False, visible_sources=None):
        policy = run.context.get('model_policy') or self.router.policy()
        route = self.router.route(policy,stage)
        if route.connection_id:self.router.connections.adapter(route,run.owner_id)
        input_hash = digest({'messages':messages,'snapshot':run.snapshot_id,'route':policy['routes'][stage]})
        reserve = sum(len(m['content'].encode()) for m in messages)+PARAMETERS['output_tokens_max']+256
        call_id = str(uuid4())
        sources = [{'id':'user-material','source_type':'user_provided','hash':digest(run.context.get('material',''))}]
        sources += [{k:s.get(k) for k in ('source_id','document_id','version','url','source_type')}|{'content_hash':digest(s.get('text',''))} for s in run.context.get('evidence',[])]
        if run.context.get('operations'):
            sources.append({'id':'account-context','account_id':run.context['operations'].get('account_id'),'hash':digest(run.context['operations'])})
        if visible_sources is not None:
            sources = visible_sources
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            guard(db)
            from backend.knowledge import assert_public_model_evidence
            assert_public_model_evidence(self.store,run,db)
            if reuse:
                old = db.execute('SELECT c.id,c.response_json,c.actual,c.state FROM live_calls c JOIN model_audit a ON a.call_id=c.id WHERE c.run_id=? AND a.input_hash=? AND c.stage=?',(run.run_id,input_hash,stage)).fetchone()
                if old:
                    require(old[1] is not None and old[2] is not None,'USAGE_UNKNOWN','上次调用结果或用量未知；已停止，未重复收费调用')
                    if old[3] == 'invalid':
                        raw=json.loads(old[1])
                        if getattr(run, 'workflow_type', 'creation') == 'windtunnel':
                            from backend.windtunnel import STAGES, normalize
                            require(stage in STAGES, 'MODEL_OUTPUT_INVALID', '无效风洞阶段不能复用')
                            # Revalidate a received response under current strict
                            # domain rules; never resend or rewrite the raw audit.
                            normalize(run,stage,raw)
                        else:
                            from backend.citation_ids import repair
                            from backend.live import material_records, normalize, bounded_title_candidates
                            _,repairs=repair(stage,raw,material_records(run.context))
                            _,title_adjustment=bounded_title_candidates(run,raw) if stage=='title' else (raw,None)
                            require(repairs or title_adjustment,'MODEL_OUTPUT_INVALID','上次输出未通过校验，已停止重复调用；请查看被拒绝的模型响应')
                            normalize(run,stage,raw)
                    return json.loads(old[1]),old[2],old[0]
            db.execute('INSERT INTO live_lineage VALUES(?,?) ON CONFLICT(run_id) DO NOTHING',(run.run_id,run.run_id))
            root=db.execute('SELECT budget_id FROM live_lineage WHERE run_id=?',(run.run_id,)).fetchone()[0]
            if agent=='content' and stage in ('body','revise'):
                stage_count=db.execute(f"SELECT COUNT(*) FROM live_calls WHERE run_id IN ({FAMILY}) AND agent='content' AND stage IN ('body','revise')",(root,)).fetchone()[0]
            else:
                stage_count=db.execute(f'SELECT COUNT(*) FROM live_calls WHERE run_id IN ({FAMILY}) AND agent=? AND stage=?',(root,agent,stage)).fetchone()[0]
            require(stage_count<CONTRACT['runtime_extension']['stage_attempts_max'],'STAGE_ATTEMPT_LIMIT','同一步已达到3次调用上限（含首次）')
            count,used=db.execute(f'SELECT COUNT(*),COALESCE(SUM(COALESCE(actual,reserved)),0) FROM live_calls WHERE run_id IN ({FAMILY})',(root,)).fetchone()
            cost_sql = 'SELECT COALESCE(SUM(COALESCE(c.actual,c.reserved)*COALESCE(a.rate,?)),0) FROM live_calls c LEFT JOIN model_audit a ON a.call_id=c.id '
            cost=db.execute(cost_sql+f'WHERE c.run_id IN ({FAMILY})',(RATE,root)).fetchone()[0]
            billing_owner=run.owner_id if route.billing_source=='user' else ''
            daily=db.execute(cost_sql+"WHERE CAST(c.created AS date)=CURRENT_DATE AND COALESCE(a.billing_source,'platform')=? AND COALESCE(a.billing_owner,'')=?",(RATE,route.billing_source,billing_owner)).fetchone()[0] if self.store.postgres else db.execute(cost_sql+"WHERE date(c.created)=date('now') AND COALESCE(a.billing_source,'platform')=? AND COALESCE(a.billing_owner,'')=?",(RATE,route.billing_source,billing_owner)).fetchone()[0]
            if route.billing_source=='user':
                daily+=db.execute('SELECT COALESCE(SUM(COALESCE(tokens,reserved)*rate),0) FROM model_connection_tests WHERE owner=? AND started>?',(run.owner_id,time.time()-86400)).fetchone()[0]
            require(count<PARAMETERS['run_attempts_max'],'BUDGET_EXCEEDED',f'调用次数已达上限：{count}/{PARAMETERS["run_attempts_max"]}')
            require(used+reserve<=PARAMETERS['run_tokens_max'],'BUDGET_EXCEEDED',f'Token预留不足：已计入 {used}，下一步保守预留 {reserve}，上限 {PARAMETERS["run_tokens_max"]}；预留不等于实际消费')
            require(cost+reserve*route.rate<=(route.run_budget_usd if route.billing_source=='user' else min(route.run_budget_usd or self.config.run_budget_usd,self.config.run_budget_usd)),'BUDGET_EXCEEDED','本任务费用预留将超过上限；未发起调用')
            require(daily+reserve*route.rate<=(route.day_budget_usd if route.billing_source=='user' else min(route.day_budget_usd or self.config.day_budget_usd,self.config.day_budget_usd)),'BUDGET_EXCEEDED','今日费用预留将超过上限；未发起调用')
            from backend.testing_budget import reserve as reserve_testing_budget
            reserve_testing_budget(db,run,root,route,messages,call_id)
            db.execute('INSERT INTO live_calls(id,run_id,agent,stage,reserved,state) VALUES(?,?,?,?,?,?)',(call_id,run.run_id,agent,stage,reserve,'calling'))
            db.execute('INSERT INTO model_audit(call_id,run_id,agent,stage,provider,model,route_version,prompt_version,input_hash,sources,snapshot_id,started,rate,outcome) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(call_id,run.run_id,agent,stage,route.provider,route.model,policy['version'],policy['prompt_version'],input_hash,json.dumps(sources),run.snapshot_id,time.time(),route.rate,'calling'))
            db.execute('UPDATE model_audit SET billing_source=?,billing_owner=?,connection_id=? WHERE call_id=?',(route.billing_source,billing_owner,route.connection_id,call_id))
        started=time.monotonic()
        try:
            value,tokens,meta=self.router.complete(route,messages,run.owner_id)
            require(type(tokens) is int and 0<=tokens<=reserve,'MODEL_OUTPUT_INVALID','用量报告异常，保留预算预留')
            with self.store.connect() as db:
                db.execute("UPDATE live_calls SET actual=?,state='received',response_json=? WHERE id=?",(tokens,json.dumps(value,ensure_ascii=False),call_id))
                db.execute("UPDATE model_audit SET outcome='received',duration_ms=?,request_id=?,input_tokens=?,output_tokens=? WHERE call_id=?",(round((time.monotonic()-started)*1000),meta.get('request_id'),meta.get('input_tokens'),meta.get('output_tokens'),call_id))
            return value,tokens,call_id
        except Exception as error:
            safe=str(error) if isinstance(error,DomainError) else '模型调用失败，未自动重试'
            with self.store.connect() as db:
                db.execute("UPDATE live_calls SET state='failed',error=? WHERE id=?",(safe,call_id))
                db.execute("UPDATE model_audit SET outcome='failed',duration_ms=? WHERE call_id=?",(round((time.monotonic()-started)*1000),call_id))
            raise DomainError('PROVIDER_ERROR',safe) from None

    def validated(self, call_id, error):
        with self.store.connect() as db:
            state='invalid' if error else 'validated'
            db.execute('UPDATE live_calls SET state=?,error=? WHERE id=?',(state,error,call_id))
            db.execute('UPDATE model_audit SET outcome=? WHERE call_id=?',(state,call_id))

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


class ModelRouter:
    def __init__(self, config, client=None, routes=None, adapters=None):
        self.config = config
        self.routes = routes if routes is not None else {s:Route('deepseek',**v) for s,v in config.routes.items()}
        self.adapters = adapters or {}
        self.client = client

    def policy(self, workflow_type='creation'):
        require(workflow_type in ('creation','windtunnel','operations'),'INVALID_INPUT','工作流类型无效')
        stages = {'windtunnel':WINDTUNNEL_STAGES,'operations':OPERATIONS_STAGES}.get(workflow_type,CREATION_STAGES)
        routes = {s: asdict(self.routes.get(s, Route('fixture' if self.client else 'deepseek', self.config.model))) for s in stages}
        prompt={'windtunnel':'windtunnel.v1','operations':'operations_plan.v1'}.get(workflow_type,CONTRACT['runtime_extension']['prompt_version'])
        return {'version':digest(routes), 'routes':routes, 'prompt_version':prompt}

    def route(self, policy, stage):
        require(stage in STAGES and stage in policy.get('routes',{}) and policy.get('version') == digest(policy.get('routes')), 'CONFIG_INVALID','模型路由快照无效')
        route = Route(**policy['routes'][stage])
        require(isinstance(route.rate,(int,float)) and 0 < route.rate < 1, 'CONFIG_INVALID','模型费率上限无效')
        require(route.provider == 'deepseek' or self.client is not None or (route.provider,route.model) in self.adapters, 'CONFIG_INVALID','未注册的模型适配器')
        return route

    def complete(self, route, messages):
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
        input_hash = digest({'messages':messages,'snapshot':run.snapshot_id,'route':asdict(route)})
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
            if reuse:
                old = db.execute('SELECT c.id,c.response_json,c.actual,c.state FROM live_calls c JOIN model_audit a ON a.call_id=c.id WHERE c.run_id=? AND a.input_hash=? AND c.stage=?',(run.run_id,input_hash,stage)).fetchone()
                if old:
                    require(old[1] is not None and old[2] is not None,'USAGE_UNKNOWN','上次调用结果或用量未知；已停止，未重复收费调用')
                    require(old[3] != 'invalid','MODEL_OUTPUT_INVALID','上次输出未通过校验；请核对后新建任务')
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
            daily=db.execute(cost_sql+"WHERE date(c.created)=date('now')",(RATE,)).fetchone()[0]
            require(count<PARAMETERS['run_attempts_max'] and used+reserve<=PARAMETERS['run_tokens_max'] and cost+reserve*route.rate<=self.config.run_budget_usd and daily+reserve*route.rate<=self.config.day_budget_usd,'BUDGET_EXCEEDED','已到调用、Token 或费用预留上限')
            db.execute('INSERT INTO live_calls(id,run_id,agent,stage,reserved,state) VALUES(?,?,?,?,?,?)',(call_id,run.run_id,agent,stage,reserve,'calling'))
            db.execute('INSERT INTO model_audit(call_id,run_id,agent,stage,provider,model,route_version,prompt_version,input_hash,sources,snapshot_id,started,rate,outcome) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(call_id,run.run_id,agent,stage,route.provider,route.model,policy['version'],policy['prompt_version'],input_hash,json.dumps(sources),run.snapshot_id,time.time(),route.rate,'calling'))
        started=time.monotonic()
        try:
            value,tokens,meta=self.router.complete(route,messages)
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

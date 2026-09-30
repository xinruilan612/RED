"""Evidence-grounded weekly planning with one explicit, budgeted model call."""
import json
import time
from datetime import date, timedelta
from uuid import uuid4

from backend.accounts import find_account
from backend.contracts import DomainError, require
from backend.workflow import Run, digest


def _items(value):
    return [x.strip() for x in value.replace('，', ',').replace('、', ',').split(',') if x.strip()]


def build_snapshot(state, account_id, source_type):
    account = find_account(state, account_id)
    profile = account['profile']
    pubs = [p for p in state['publications'] if p.get('account_id') == account_id
            and p.get('provenance') == source_type and p.get('published_at')]
    pub_ids = {p['id'] for p in pubs}
    metrics = [m for m in state['metrics'] if m.get('publication_id') in pub_ids and m.get('source_type') == source_type]
    memories = [m for m in state['memories'] if m.get('account_id') == account_id
                and m.get('source_type') == source_type and m.get('status') == 'accepted']
    signals = [s for s in state.get('signals', []) if s.get('account_id') == account_id]
    hypotheses = [h for h in state.get('hypotheses', []) if h.get('account_id') == account_id
                  and h.get('ledger_status') == 'accepted']
    trends = [t for t in state.get('trends', []) if t.get('platform') == account['platform']
              and t.get('source_type') == 'manual']
    refs = [{'id': 'profile:'+k, 'label': '账号档案：'+k} for k in
            ('positioning','audience','tone','pillars','goal','resources','banned')]
    for row in pubs: refs.append({'id':'post:'+row['id'],'label':'已发布作品'})
    for row in metrics: refs.append({'id':'metric:'+row['id'],'label':'作品指标（用户记录）'})
    for row in memories: refs.append({'id':'memory:'+row['id'],'label':'已确认复盘经验'})
    for row in signals: refs.append({'id':'signal:'+row['id'],'label':'用户记录的需求信号'})
    for row in hypotheses: refs.append({'id':'hypothesis:'+row['id'],'label':'已确认实验假设'})
    for row in trends: refs.append({'id':'trend:'+row['id'],'label':'用户录入的公开观察'})
    pub_titles = {p['id']:p.get('content',{}).get('selected_title','') for p in pubs}
    recent = [{'id':p['id'],'title':pub_titles[p['id']],'published_at':p['published_at'],
               'format':p.get('format'),'pillar':p.get('pillar')}
              for p in pubs[:20]]
    metric_rows = [{'id':m['id'],'publication_id':m['publication_id'],'title':pub_titles.get(m['publication_id']),
                    'window':m.get('window'),'observed_at':m.get('observed_at'),'values':m.get('values',{})}
                   for m in metrics[-30:]]
    mem_rows = [{'id':m['id'],'text':m.get('text'),'limitation':m.get('limitation')}
                for m in memories[:10]]
    signal_rows = [{'id':s['id'],'kind':s.get('kind'),'text':s.get('text'),'sample_size':s.get('sample_size'),
                    'collection_method':s.get('collection_method'),'source_url':s.get('source_url')}
                   for s in signals[:10]]
    gaps=[]
    if not pubs: gaps.append('当前账号在所选来源下没有已发布作品记录')
    if not metrics: gaps.append('没有可用于判断表现的作品指标')
    if not memories: gaps.append('没有已确认的复盘经验')
    if not signals: gaps.append('没有记录评论需求或搜索意图')
    return {
        'account_id':account_id,'account_name':account['name'],'platform':account['platform'],
        'profile':{k:profile.get(k,'') for k in ('positioning','audience','tone','pillars','goal','resources','banned')}
                 | {'weekly_frequency':profile['weekly_frequency']},
        'recent_posts':recent,'metrics':metric_rows,'accepted_memories':mem_rows,
        'user_recorded_signals':signal_rows,
        'accepted_hypotheses':[{'id':h['id'],'statement':h.get('statement'),'objective':h.get('objective'),
                                'falsifier':h.get('falsifier')} for h in hypotheses[:8]],
        'manual_trend_observations':[{'id':t['id'],'title':t.get('title'),'angle':t.get('angle'),
                                      'reason':t.get('reason'),'source_url':t.get('source_url')}
                                     for t in trends[:8]],
        'available_basis_refs':refs,'data_gaps':gaps,
    }


def prompt_for(snapshot, week_start, source_type):
    system = '''你是有迹的账号运营策划 Agent。只依据输入中的当前账号档案、作品、用户录入信号、真实记录指标和已确认经验制定一周可执行计划。
不要把模拟记录说成真实表现；source_type=simulation 时明确标记为演示数据。没有记录就说没有，不推断涨粉、爆款或因果。目标决定内容组合：涨粉要有吸引新受众、证明方法、展示差异、建立信任等不同任务；卖货要覆盖使用场景、产品证据、比较/顾虑、购买行动；获客要呈现问题、过程、案例、适配对象和低门槛下一步。仅作为按账号情况选择的策划思路，不是固定模板。
计划必须贴合账号平台、定位、受众、栏目、表达风格、禁用表达及时间/素材条件。根据已发布作品主动避免简单重复；每篇需有不同标题、格式或切入角度。按目标受众真正能做的下一步设计成功信号，不许保证结果。作品少或数据空缺时在 data_gaps 明说，并在理由里说明本条主要由档案假设而来。basis_refs 只能引用输入提供的 available_basis_refs 中的 id；没有来源支撑时用 profile 字段引用，且在 data_gaps 说明。
只返回符合此 JSON 结构的对象：{"weekly_summary":"...","data_gaps":["..."],"tasks":[{"day_offset":0,"pillar":"...","title":"...","format":"...","angle":"...","action":"...","reason":"...","success_signal":"...","basis_refs":["profile.goal"]}]}。tasks 数量必须等于 weekly_frequency，day_offset 为 0-6 且互不重复。不得输出 markdown。'''
    user = {'week_start':week_start,'source_type':source_type,
            'allowed_pillars':_items(snapshot['profile']['pillars']) or ['常青内容'],
            'account_reality':snapshot}
    return [{'role':'system','content':system},{'role':'user','content':json.dumps(user,ensure_ascii=False)}]


def validate_plan(result, snapshot):
    require(isinstance(result,dict) and set(result)=={'weekly_summary','data_gaps','tasks'},
            'MODEL_OUTPUT_INVALID','计划字段不完整')
    summary=result['weekly_summary']; gaps=result['data_gaps']; tasks=result['tasks']
    require(isinstance(summary,str) and 5<=len(summary)<=500 and isinstance(gaps,list)
            and len(gaps)<=20 and all(isinstance(x,str) and len(x)<=300 for x in gaps),
            'MODEL_OUTPUT_INVALID','计划说明格式无效')
    count=snapshot['profile']['weekly_frequency']
    require(isinstance(tasks,list) and len(tasks)==count,'MODEL_OUTPUT_INVALID','计划篇数与账号档案不符')
    refs={x['id'] for x in snapshot['available_basis_refs']}
    fields={'day_offset','pillar','title','format','angle','action','reason','success_signal','basis_refs'}
    offsets=[]; titles=[]
    for task in tasks:
        require(isinstance(task,dict) and set(task)==fields,'MODEL_OUTPUT_INVALID','待办格式无效')
        require(type(task['day_offset']) is int and 0<=task['day_offset']<=6,'MODEL_OUTPUT_INVALID','计划日期超出本周')
        offsets.append(task['day_offset'])
        for key,limit in (('pillar',100),('title',160),('format',80),('angle',240),('action',300),('reason',600),('success_signal',240)):
            require(isinstance(task[key],str) and task[key].strip() and len(task[key])<=limit,'MODEL_OUTPUT_INVALID','计划内容缺失或过长')
        titles.append(task['title'].strip().casefold())
        require(isinstance(task['basis_refs'],list) and task['basis_refs'] and
                all(ref in refs for ref in task['basis_refs']),'MODEL_OUTPUT_INVALID','计划引用了不存在的依据')
    require(len(set(offsets))==count and len(set(titles))==count,'MODEL_OUTPUT_INVALID','计划日期或标题重复')
    if count>=3:
        require(len({t['angle'].strip().casefold() for t in tasks})>=3,'MODEL_OUTPUT_INVALID','多篇计划的切入角度过于重复')
        require(len({t['format'].strip().casefold() for t in tasks})>=2,
                'MODEL_OUTPUT_INVALID','本周内容形式过于单一')
    pillars=_items(snapshot['profile']['pillars']) or ['常青内容']
    require(all(t['pillar'] in pillars for t in tasks),'MODEL_OUTPUT_INVALID','计划栏目与账号档案不匹配')
    return result


class OperationsPlanner:
    def __init__(self, store, operations, executor):
        self.store,self.operations,self.executor=store,operations,executor

    def generate(self, owner, data):
        require(isinstance(data,dict) and set(data)=={'account_id','week_start','source_type','version','key'},'INVALID_INPUT','计划请求字段无效')
        require(data['source_type'] in ('manual','simulation'),'INVALID_INPUT','计划数据来源无效')
        require(isinstance(data['key'],str) and 16<=len(data['key'])<=100,'INVALID_INPUT','请刷新后重新生成计划')
        try: start=date.fromisoformat(data['week_start'])
        except (TypeError,ValueError): raise DomainError('INVALID_INPUT','周开始日期无效') from None
        require(start.weekday()==0,'INVALID_INPUT','请选择周一作为计划开始日期')
        self.executor.calls.config=self.executor.config
        router=self.executor.router; policy=router.policy('operations')
        fixture=all(r['provider']=='fixture' for r in policy['routes'].values())
        require(self.executor.config.ready or fixture,'KEY_REQUIRED','请先配置模型 API Key；生成前不会自动调用模型')
        fingerprint=digest({k:v for k,v in data.items() if k!='key'})
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT fingerprint,status,response,error FROM operations_plan_attempts WHERE owner=? AND key=?',(owner,data['key'])).fetchone()
            if previous:
                require(previous[0]==fingerprint,'IDEMPOTENCY_CONFLICT','该请求标识已用于另一份计划')
                if previous[1]=='done': return json.loads(previous[2])
                raise DomainError('PLAN_ATTEMPT_EXISTS',previous[3] or '上次生成尚未完成；为避免重复收费，请勿重试同一请求')
            state=self.operations.read(owner,db)
            require(state['version']==data['version'],'VERSION_CONFLICT','账号或历史记录已更新，请刷新后重新生成')
            account=find_account(state,data['account_id'])
            require(not any(p['account_id']==account['id'] and p['week_start']==start.isoformat()
                            and p['source_type']==data['source_type'] and p['status'] in ('draft','accepted') for p in state['plans']),
                    'DUPLICATE','本周已有有效计划；撤销后可重新生成')
            require(not db.execute("SELECT 1 FROM operations_plan_attempts WHERE owner=? AND account_id=? AND week_start=? AND status='running'",
                                   (owner,account['id'],start.isoformat())).fetchone(),
                    'PLAN_IN_PROGRESS','当前账号本周已有计划正在生成，请稍候')
            snapshot=build_snapshot(state,account['id'],data['source_type'])
            db.execute('INSERT INTO operations_plan_attempts(owner,key,fingerprint,account_id,week_start,status,created_at) VALUES(?,?,?,?,?,?,?)',
                       (owner,data['key'],fingerprint,account['id'],start.isoformat(),'running',time.time()))
        run=Run(owner_id=owner,snapshot_id=digest(snapshot),context={'model_policy':policy,'operations':snapshot,'material':''})
        route=router.route(policy,'operations_plan')
        call_id=None
        try:
            def guard(db):
                current=self.operations.read(owner,db)
                require(current['version']==data['version'],'VERSION_CONFLICT','生成期间账号或记录已更新；本次结果不会写入日历')
                claim=db.execute('SELECT status FROM operations_plan_attempts WHERE owner=? AND key=?',(owner,data['key'])).fetchone()
                require(claim and claim[0]=='running','VERSION_CONFLICT','计划请求已失效')
            value,tokens,call_id=self.executor.calls.invoke(run,'operations_planner','operations_plan',prompt_for(snapshot,start.isoformat(),data['source_type']),guard,
                visible_sources=[{'source_id':r['id'],'source_type':r['label']} for r in snapshot['available_basis_refs']])
            try: value=validate_plan(value,snapshot)
            except DomainError as error:
                self.executor.calls.validated(call_id,str(error));raise
            value['data_gaps']=list(dict.fromkeys(snapshot['data_gaps']+value['data_gaps']))
            self.executor.calls.validated(call_id,None)
            tasks=[]
            for task in value['tasks']:
                tasks.append({'id':str(uuid4()),'date':(start+timedelta(days=task['day_offset'])).isoformat(),
                    'title':task['title'],'pillar':task['pillar'],'format':task['format'],'angle':task['angle'],
                    'action':task['action'],'success_signal':task['success_signal'],'basis_refs':task['basis_refs'],
                    'reason':task['reason'],'status':'planned','publication_id':None})
            usage={'call_id':call_id,'provider':route.provider,'model':route.model,'stage':'operations_plan',
                   'model_calls':1,'tokens':tokens,'cost_estimate_usd':round(tokens*route.rate,6),'currency':'USD'}
            payload={'account_id':account['id'],'week_start':start.isoformat(),'source_type':data['source_type'],
                'profile_revision':account['revision'],'goal':snapshot['profile']['goal'] or '先验证目标受众是否需要这类内容',
                'context_fingerprint':digest(snapshot),
                'profile_snapshot':{'positioning':snapshot['profile']['positioning'],'audience':snapshot['profile']['audience'],
                    'pillars':snapshot['profile']['pillars'],'goal':snapshot['profile']['goal'],
                    'resources':snapshot['profile']['resources'],'weekly_frequency':snapshot['profile']['weekly_frequency']},
                'memory_refs':[m['id'] for m in snapshot['accepted_memories']],
                'weekly_summary':value['weekly_summary'],'data_gaps':value['data_gaps'],'basis_refs':snapshot['available_basis_refs'],
                'execution':usage,'tasks':tasks}
            committed=self.operations.command(owner,{'action':'create_agent_plan','payload':payload,'version':data['version'],'key':'agent-plan:'+data['key']},internal=True)
            response={'operations':committed,'plan':committed['plans'][0]}
            with self.store.connect() as db:
                db.execute("UPDATE operations_plan_attempts SET status='done',response=? WHERE owner=? AND key=?",
                           (json.dumps(response,ensure_ascii=False),owner,data['key']))
            return response
        except Exception as error:
            safe=str(error) if isinstance(error,DomainError) else '模型计划未能完成；为避免重复收费，本次未自动重试'
            with self.store.connect() as db:
                db.execute("UPDATE operations_plan_attempts SET status='failed',error=? WHERE owner=? AND key=? AND status='running'",
                           (safe,owner,data['key']))
            raise

"""Deterministic, visibly labelled simulation. No model, network or API key."""
import copy
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from backend.contracts import CONTRACT, require

SCENARIOS = ('standard', 'revision', 'missing')


def validate_text(value, label, maximum, allow_empty=False):
    require(isinstance(value, str) and len(value) <= maximum and (allow_empty or value.strip()),
            'INVALID_INPUT', f'{label}不能为空且不能超过 {maximum} 字')
    return value.strip()


def validate_brief(data):
    require(isinstance(data, dict), 'INVALID_INPUT', '需求格式无效')
    require(set(data) <= {'topic','audience','tone','material','allow_hypothesis','scenario'}, 'INVALID_INPUT', '未知需求字段')
    result = {key:validate_text(data.get(key,''), label, limit, empty) for key,label,limit,empty in (
        ('topic','创作主题',100,False), ('audience','目标读者',200,False),
        ('tone','表达风格',100,False), ('material','真实素材',8000,True))}
    result['scenario'] = data.get('scenario','standard')
    require(result['scenario'] in SCENARIOS, 'INVALID_INPUT', '演示场景无效')
    result['allow_hypothesis'] = data.get('allow_hypothesis', True)
    require(type(result['allow_hypothesis']) is bool, 'INVALID_INPUT', '假设授权必须为布尔值')
    return result


def validate_edit(data):
    require(isinstance(data,dict) and set(data)=={'selected_title','body','cta','tags'}, 'INVALID_INPUT','编辑字段无效')
    result = {k:validate_text(data[k],label,limit,empty) for k,label,limit,empty in (
        ('selected_title','标题',200,False),('body','正文',6000,False),('cta','互动引导',500,True))}
    require(isinstance(data['tags'],list) and len(data['tags'])<=10, 'INVALID_INPUT','最多十个标签')
    result['tags']=[validate_text(t,'标签',40) for t in data['tags']]
    return result


def node(agent, stage, inputs, function):
    started = time.perf_counter()
    output = function()
    return {'agent':agent,'stage':stage,'mode':'simulation','input':inputs,'output':output,
            'duration_ms':round((time.perf_counter()-started)*1000,3),
            'model_calls':0,'tokens':0,'cost':0,'tools':[],
            'memory':'仅使用本次输入；尚未接入跨任务记忆'}


def record(run, result):
    result['snapshot_id']=run.snapshot_id
    result['id']=str(uuid4())
    run.node_runs.append(result)
    run.event('agent.completed', agent=result['agent'],stage=result['stage'],node_ref=result['id'],mode='simulation')


def audience(context):
    return {'sample_size':0,'status':'needs_data','primary_audience':context['audience'],
            'confidence':'low','basis':'依据本次需求的模拟假设，未分析历史表现',
            'pain_points':['希望获得与主题有关、可跟做的具体步骤'],
            'content_opportunities':['用清晰步骤组织内容，邀请读者自行验证效果']}


def research(context):
    material=context['material']
    gap=context['scenario']=='missing' and not material.strip()
    return {'core_gap':gap,'status':'insufficient' if gap else ('ready' if material else 'partial'),
            'sources':[{'source_id':'user-material','text':material,'source_type':'user_provided',
                        'verification':'用户提供，未独立核实'}] if material else [],
            'gaps':['该演示要求真实素材，请在人工处理区补充'] if gap else [],
            'scope':'仅收录用户输入；没有联网搜索，也没有事实核验',
            'prohibited_claims':['未经验证的效果数字','虚构亲身经历']}


def latest(run, stage):
    return next(a['value'] for a in reversed(run.artifacts) if a['stage']==stage)


def make_content(run, stage):
    c=run.context; topic=c['topic']
    if stage=='strategy':
        return {'angle':f'把「{topic}」拆成可尝试的小步骤','reader':c['audience'],
                'promise':'提供尝试方法，不承诺实际收益','tone':c['tone'],
                'assumptions':['读者需求仅来自输入，尚未由历史数据验证']}
    if stage=='outline':
        return ['说明使用场景','给出三个尝试步骤','回看结果并提出问题']
    if stage=='hook':
        return f'想试试{topic}，可以先从一个小步骤开始。'
    if stage=='title':
        titles=[f'{topic}：从一个小步骤开始', f'关于{topic}，先试这三个步骤',
                f'给初学者的{topic}尝试清单',f'{topic}，怎么开始更清楚？',f'把{topic}拆成一次小练习']
        selected='必爆！'+titles[0] if c['scenario']=='revision' else titles[0]
        if selected not in titles: titles[0]=selected
        return {'candidates':titles,'selected':selected,
                'note':'返修演示故意加入「必爆」，供规则审核发现' if c['scenario']=='revision' else '模拟候选，不代表真实传播表现'}
    material=('\n\n你的素材（用户自述，未核验）：\n'+c['material']) if c['material'] else ''
    return {'selected_title':latest(run,'title')['selected'],
            'body':latest(run,'hook')+'\n\n① 选一个具体场景，写下你想解决的问题。\n\n② 围绕这个场景尝试一个可执行步骤，记录过程。\n\n③ 回看结果：哪些有用，哪些需要调整？先验证，再决定是否继续。'+material,
            'cta':'你准备先尝试哪一步？','tags':['创作笔记','尝试清单']}


def review(run):
    draft=run.drafts[-1]; text=draft['content']; issues=[]
    # This small rule set is not a semantic or platform compliance reviewer.
    for field in ('selected_title','body','cta','tags'):
        value=' '.join(text.get(field,[])) if field=='tags' else text.get(field,'')
        for word in ('必爆','保证收益','百分之百有效'):
            if word in value:
                issues.append({'issue_id':f'{field}:{word}','severity':'major','state':'open',
                               'location':field,'excerpt':word,'reason':'确定性效果承诺，模拟规则要求修改',
                               'suggestion':f'删除「{word}」，改为可验证的尝试建议'})
    decision='revision_required' if issues else 'approved'
    old=run.prior_review['issues'] if run.prior_review else []
    ids={i['issue_id'] for i in issues}
    checks=[{'name':name,'result':('fail' if name=='title_body_alignment' and issues else 'pass'),
             'basis':'仅模拟检查；未调用模型或核验外部事实'} for name in CONTRACT['review_policy']['checks']]
    return {'ref':str(uuid4())+'@1','draft_ref':draft['ref'],'snapshot_id':run.snapshot_id,
            'content_hash':draft['content_hash'],'policy_ref':'demo-rules@1','mode':'simulation',
            'decision':decision,'next_action':'revise' if issues else 'await_user_confirmation',
            'checks':checks,'issues':issues,'previous_issue_results':[
                {'issue_id':i['issue_id'],'result':'unresolved' if i['issue_id'] in ids else 'resolved'} for i in old],
            'limitations':['模拟审核只检测少量明确词语；通过不代表事实、原创或平台合规通过'], 'human_questions':[]}


def advance(run):
    require(run.context, 'INVALID_INPUT','这不是网页模拟任务')
    require(run.run_status in ('QUEUED','RUNNING'), 'INVALID_TRANSITION','请先处理人工操作')
    if run.run_status=='QUEUED': run.start()
    if run.current_stage=='brief':
        for agent in ('audience','research'): run.event('agent.started',agent=agent,mode='simulation')
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks=[pool.submit(node,a,'analysis',copy.deepcopy(run.context),lambda f=f:f(run.context))
                   for a,f in [('audience',audience),('research',research)]]
            results=[t.result() for t in tasks]
        for result in results:
            record(run,result)
            run.branch(result['agent'],run.snapshot_id,'succeeded',result['output'])
        run.join(run.context['allow_hypothesis'])
        return
    if run.current_stage=='content':
        run.event('agent.started',agent='content',mode='simulation')
        if run.review and run.review['decision']=='revision_required':
            content=copy.deepcopy(run.drafts[-1]['content'])
            for issue in run.review['issues']:
                field=issue['location']
                if field=='tags': content[field]=[t.replace(issue['excerpt'],'') for t in content[field]]
                else: content[field]=content[field].replace(issue['excerpt'],'').lstrip('！! ')
            result=node('content','revise',{'issues':run.review['issues'],'previous_draft':run.drafts[-1]['ref']},lambda:content)
            record(run,result); run.draft(content)
            return
        stages=CONTRACT['content_stages']; done={a['stage'] for a in run.artifacts}
        stage=next(s for s in stages if s not in done)
        result=node('content',stage,{'brief':run.context,'branches':run.branches,
                                   'upstream':copy.deepcopy(run.artifacts)},lambda:make_content(run,stage))
        record(run,result)
        run.artifacts.append({'stage':stage,'value':result['output'],'snapshot_id':run.snapshot_id})
        run.event('artifact.created',stage=stage,mode='simulation')
        if stage=='body': run.draft(result['output'])
        return
    if run.current_stage=='reviewer':
        run.event('agent.started',agent='reviewer',mode='simulation')
        result=node('reviewer','review',copy.deepcopy(run.drafts[-1]),lambda:review(run))
        record(run,result)
        # Trusted simulation-only guards. No browser-supplied booleans are consumed.
        gates={k:True for k in CONTRACT['review_policy']['required_gates']}
        run.reviewed(result['output'],gates)
        return
    require(False,'INVALID_TRANSITION','未知执行阶段')


def actions(run):
    result=[]
    if run.run_status in ('QUEUED','RUNNING'): result+=['next']
    if run.run_status not in CONTRACT['terminal_states']: result+=['cancel']
    if run.run_status=='WAITING_USER':
        if run.wait_reason=='final_confirmation': result+=['edit','accept']
        if run.wait_reason in ('missing_material','hypothesis_permission') and run.supplements < 1: result+=['supplement']
    if run.run_status=='RUNNING' and run.review and run.review['decision']=='revision_required': result+=['edit']
    if run.run_status=='SUCCEEDED': result+=['export']
    return result

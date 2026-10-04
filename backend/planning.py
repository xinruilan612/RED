"""Account-scoped weekly plans and due reviews. No background publishing or model calls."""
from datetime import date, timedelta, datetime, timezone
from uuid import uuid4

from backend.accounts import find_account
from backend.analytics import latest_metrics, window_quality, WINDOW_HOURS, parsed, refresh_plans
from backend.contracts import require
from backend.demo import validate_text


def _items(value):
    return [part.strip() for part in value.replace('，', ',').replace('、', ',').replace('\n', ',').split(',') if part.strip()]


def _resource_note(resources):
    notes = []
    if any('少于 2 小时' in item or '少于2小时' in item for item in resources):
        notes.append('轻量制作')
    elif any('2–4 小时' in item or '2-4 小时' in item for item in resources):
        notes.append('控制制作量')
    if any('已有可用照片或视频素材' in item for item in resources):
        notes.append('优先用已拍素材')
    if any('主要用手机拍摄' in item for item in resources):
        notes.append('手机可完成')
    return '，'.join(notes)


def _goal_action(goal, pillar, resources):
    value = goal.lower()
    if any(word in value for word in ('涨粉', '关注', '粉丝')):
        action = '用拍摄前后对比讲清一个新手能复用的方法'
    elif any(word in value for word in ('卖货', '销售', '订单', '转化', '成交', '商品浏览', '查看商品')):
        action = '展示真实使用场景、适合人群和需要说明的限制'
    elif any(word in value for word in ('获客', '线索', '报名', '注册', '推广', '咨询', '预约', '到店', '约拍', '进店', '引导试用')):
        action = '解决一个具体问题，并说明读者可以采取的下一步'
    elif any(word in value for word in ('互动', '收藏', '评论', '参与')):
        action = '整理成读者能收藏照做的步骤清单'
    elif any(word in value for word in ('个人品牌', '人设', '信任')):
        action = '分享一次拍摄幕后过程和自己的选择理由'
    elif any(word in value for word in ('验证', '测试', '实验')):
        action = '围绕一个明确假设制作内容，并一次只测试一个表达点'
    else:
        action = '讲清一个具体场景、实用方法和读者可采取的行动'
    note = _resource_note(resources)
    resource_prefix = note + '，' if note else ''
    return f'围绕「{pillar}」{resource_prefix}{action}'


RULE_TASKS = (
    ('先做哪一步？', '入门步骤', '步骤说明',
     '选一个自己能验证的操作，准备所需材料，记录起点、第一步和完成状态；没有材料时先补资料。',
     '检查读者是否能找到第一步及所需条件；暂不把阅读量当作学会的证据。'),
    ('卡住时先检查什么？', '问题排查', '排查说明',
     '选一个可复现的卡点，记录现象、检查方法和处理后的状态；不把猜测写成确定原因。',
     '检查每个卡点是否对应可执行的检查项，并记录尚不能解释的问题。'),
    ('两种做法怎么选？', '选择与限制', '比较说明',
     '只比较自己有资料支撑的两种做法，列出使用条件、成本和限制；缺少另一种依据时先补资料。',
     '检查读者能否按自身条件作选择；无依据的优劣结论不纳入稿件。'),
    ('动手前后核对清单', '操作检查', '核对清单',
     '把已有操作资料整理为动手前、进行中和完成后的检查项，给每项配一个能观察的状态。',
     '检查清单是否能逐项勾选，并能指出没有完成的步骤，而不只是概括性建议。'),
    ('把过程讲清楚', '过程演示', '过程说明',
     '用自己可提供的截图、照片或文字记录串起一个完整过程；先核对关键步骤，不虚构亲历案例。',
     '检查过程材料是否覆盖起点到完成状态，缺失环节继续标注待补。'),
    ('一个需要验证的疑问', '条件与疑问', '问答说明',
     '列出一个目标读者可能会有的疑问，明确这是待验证的假设；有出处才写答案，否则保留待核实。',
     '记录疑问依据与答案来源；未采集反馈时不把假设写成真实用户需求。'),
    ('补上一处容易遗漏的说明', '补充与边界', '补充说明',
     '检查本周已有草稿或资料的一处缺口，补上前提、限制或下一步；尚无草稿时先整理待补材料。',
     '记录补充前后的差异，并确认新增说明有资料支撑；没有表现数据时不判断改稿有效。'),
)


def _rule_task(profile, pillar, slot, resources):
    title, angle, format_name, action, success_signal = RULE_TASKS[slot]
    audience = profile['audience'].strip()
    if audience:
        action = f'面向「{audience}」，围绕「{pillar}」：{action}'
    else:
        action = f'先明确目标读者，围绕「{pillar}」：{action}'
    note = _resource_note(resources)
    return dict(title=(note + '，' if note else '') + f'「{pillar}」：{title}',
                pillar=pillar, format=format_name, angle=angle, action=action,
                success_signal=success_signal,
                basis_refs=['profile:pillars', 'profile:audience', 'profile:positioning',
                            'profile:goal', 'profile:resources'])


def make_plan(state, data, created_at):
    require(set(data) == {'account_id','week_start','source_type'}, 'INVALID_INPUT', '计划字段无效')
    account = find_account(state, data['account_id'])
    require(data['source_type'] in ('manual','simulation'), 'INVALID_INPUT', '计划数据来源无效')
    try:
        start = date.fromisoformat(data['week_start'])
    except (ValueError, TypeError):
        require(False, 'INVALID_INPUT', '周开始日期无效')
    require(start.weekday() == 0, 'INVALID_INPUT', '请选择周一作为计划开始日期')
    require(not any(p['account_id'] == account['id'] and p['week_start'] == start.isoformat()
                    and p['source_type'] == data['source_type'] and p['status'] in ('draft','accepted')
                    for p in state['plans']), 'DUPLICATE', '本周已有有效计划；撤销后可重新生成')
    memories = [m for m in state['memories'] if m.get('account_id') == account['id']
                and m['source_type'] == data['source_type'] and m['status'] == 'accepted'][:3]
    profile = account['profile']
    pillars = _items(profile['pillars']) or ['常青内容']
    goal = profile['goal'] or '先验证内容是否对目标受众有用'
    resources = _items(profile['resources'])
    tasks = []
    count = account['profile']['weekly_frequency']
    for i in range(count):
        memory = memories[i] if i < len(memories) else None
        pillar = pillars[i % len(pillars)]
        task = _rule_task(profile, pillar, i, resources)
        if memory:
            task['title'] += f'；检验复盘建议：{memory["text"]}'
            task['basis_refs'].append('memory:' + memory['id'])
        reason = f'根据运营目标「{goal}」与内容栏目「{pillar}」安排；'
        reason += _goal_action(goal, pillar, resources) + '。'
        if profile['positioning']:
            reason += f'账号定位：{profile["positioning"]}。'
        reason += f'制作时考虑：{"、".join(resources)}。' if resources else '尚未填写时间 / 素材条件，可按实际情况调整。'
        reason += '计划是待确认的建议，不代表效果保证。'
        if memory:
            reason += '同时参考已接受的复盘建议，仍需再次验证。'
        else:
            reason += '暂无历史效果依据。'
        tasks.append(dict(id=str(uuid4()), date=(start+timedelta(days=(i*7)//count)).isoformat(),
            **task, reason=reason,
            memory_ref=memory['id'] if memory else None, status='planned', publication_id=None))
    data_gaps = [f'尚未填写{label}，请在执行前补充。' for field, label in
                 (('positioning', '账号定位'), ('audience', '目标读者'), ('pillars', '内容栏目'),
                  ('resources', '时间 / 素材条件')) if not profile[field].strip()]
    if not memories:
        data_gaps.append('暂无已确认的复盘建议；这些任务是档案驱动的内容思路，不是已验证的效果结论。')
    state['plans'].insert(0, dict(id=str(uuid4()), account_id=account['id'], week_start=start.isoformat(),
        source_type=data['source_type'], status='draft', created_at=created_at,
        goal=goal, profile_revision=account['revision'],
        profile_snapshot={k: profile[k] for k in ('positioning','audience','pillars','goal','resources','weekly_frequency')},
        execution=dict(stage='operations_plan', mode='rules', algorithm='profile_rules_v2', model_calls=0),
        weekly_summary='按账号档案安排不同切入点。先挑一条能提供材料的任务，核对行动与限制后再创作。',
        data_gaps=data_gaps,
        memory_refs=[m['id'] for m in memories], tasks=tasks,
        limitation='计划是可撤销的建议；不会自动创作、批准或发布。'))


def make_agent_plan(state, data, created_at):
    required={'account_id','week_start','source_type','profile_revision','goal','context_fingerprint','profile_snapshot',
              'memory_refs','weekly_summary','data_gaps','basis_refs','execution','tasks'}
    require(set(data)==required,'INVALID_INPUT','Agent 计划字段无效')
    account=find_account(state,data['account_id'])
    require(data['source_type'] in ('manual','simulation'),'INVALID_INPUT','计划数据来源无效')
    require(data['profile_revision']==account['revision'],'VERSION_CONFLICT','账号档案已更新，请重新生成计划')
    require(isinstance(data['context_fingerprint'],str) and len(data['context_fingerprint'])==64,
            'INVALID_INPUT','Agent 计划依据指纹无效')
    try:start=date.fromisoformat(data['week_start'])
    except (TypeError,ValueError):require(False,'INVALID_INPUT','周开始日期无效')
    require(start.weekday()==0,'INVALID_INPUT','请选择周一作为计划开始日期')
    require(not any(p['account_id']==account['id'] and p['week_start']==start.isoformat()
                    and p['source_type']==data['source_type'] and p['status'] in ('draft','accepted') for p in state['plans']),
            'DUPLICATE','本周已有有效计划；撤销后可重新生成')
    require(isinstance(data['tasks'],list) and len(data['tasks'])==account['profile']['weekly_frequency'],
            'INVALID_INPUT','计划篇数与账号档案不符')
    require(isinstance(data['execution'],dict) and data['execution'].get('stage')=='operations_plan'
            and data['execution'].get('model_calls')==1,'INVALID_INPUT','缺少 Agent 调用记录')
    tasks=[]
    for task in data['tasks']:
        require(set(task)=={'id','date','title','pillar','format','angle','action','success_signal','basis_refs','reason','status','publication_id'},
                'INVALID_INPUT','Agent 待办字段无效')
        try:day=date.fromisoformat(task['date'])
        except (TypeError,ValueError):require(False,'INVALID_INPUT','待办日期无效')
        require(0<=(day-start).days<=6,'INVALID_INPUT','待办日期需在计划周内')
        require(task['status']=='planned' and task['publication_id'] is None,'INVALID_INPUT','Agent 待办初始状态无效')
        tasks.append(dict(task))
    state['plans'].insert(0,dict(id=str(uuid4()),account_id=account['id'],week_start=start.isoformat(),
        source_type=data['source_type'],status='draft',created_at=created_at,goal=data['goal'],
        profile_revision=account['revision'],profile_snapshot=data['profile_snapshot'],
        context_fingerprint=data['context_fingerprint'],
        memory_refs=data['memory_refs'],weekly_summary=data['weekly_summary'],data_gaps=data['data_gaps'],
        basis_refs=data['basis_refs'],execution=data['execution'],tasks=tasks,
        limitation='AI 生成的待确认建议；依据仅限列出的账号记录，不能保证增长或转化，不会自动发布。'))


def update_plan(state, data):
    require(set(data) == {'id','status'}, 'INVALID_INPUT', '计划状态字段无效')
    plan = next((p for p in state['plans'] if p['id'] == data['id']), None)
    require(plan is not None, 'RESOURCE_NOT_FOUND', '计划不可访问')
    refresh_plans(state)
    require((plan['status'] == 'draft' and data['status'] == 'accepted') or
            (plan['status'] in ('draft','accepted','needs_review') and data['status'] == 'revoked'),
            'INVALID_TRANSITION', '当前计划需要重新生成或不能重复操作')
    plan['status'] = data['status']


def update_task(state, data):
    require(set(data) == {'plan_id','task_id','title','date','status','publication_id'}, 'INVALID_INPUT', '待办字段无效')
    plan = next((p for p in state['plans'] if p['id'] == data['plan_id']), None)
    require(plan is not None, 'RESOURCE_NOT_FOUND', '计划不可访问')
    require(plan['status'] in ('draft','accepted'), 'INVALID_TRANSITION', '计划已撤销或依据失效')
    task = next((t for t in plan['tasks'] if t['id'] == data['task_id']), None)
    require(task is not None, 'RESOURCE_NOT_FOUND', '待办不可访问')
    require(data['status'] in ('planned','done','skipped'), 'INVALID_INPUT', '待办状态无效')
    try:
        day = date.fromisoformat(data['date'])
    except (TypeError, ValueError):
        require(False, 'INVALID_INPUT', '日期无效')
    require(0 <= (day-date.fromisoformat(plan['week_start'])).days <= 6, 'INVALID_INPUT', '待办日期需在计划周内')
    if data['publication_id']:
        post = next((p for p in state['publications'] if p['id'] == data['publication_id']), None)
        require(post is not None and post['account_id'] == plan['account_id'] and post['provenance'] == plan['source_type']
                and post['published_at'], 'INVALID_INPUT', '只能关联同账号、同来源的已发布记录')
    task.update(title=validate_text(data['title'], '待办内容', 1000), date=day.isoformat(),
                status=data['status'], publication_id=data['publication_id'])


def due_reviews(state, instant=None):
    instant = instant or datetime.now(timezone.utc)
    latest = latest_metrics(state); reports = {a['metric_id'] for a in state['analyses'] if a['status'] != 'superseded'}
    tasks = []
    for post in state['publications']:
        if not post['published_at']:
            continue
        for window, hours in WINDOW_HOURS.items():
            due = parsed(post['published_at']) + timedelta(hours=hours)
            if instant < due: continue
            metric = latest.get((post['id'], window))
            quality = window_quality(post, metric)[0] if metric else 'missing'
            if metric and metric['id'] in reports: continue
            tasks.append(dict(publication_id=post['id'], account_id=post['account_id'], title=post['content']['selected_title'],
                source_type=post['provenance'], window=window, due_at=due.isoformat(), metric_id=metric['id'] if metric else None,
                state='ready' if quality == 'comparable' else 'needs_data',
                note='可复盘' if quality == 'comparable' else '窗口已到，请补录当时快照；没有当时数据可保留当前观察并注明偏差'))
    return tasks

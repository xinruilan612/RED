"""Account-scoped weekly plans and due reviews. No background publishing or model calls."""
from datetime import date, timedelta, datetime, timezone
from uuid import uuid4

from backend.accounts import find_account
from backend.analytics import latest_metrics, window_quality, WINDOW_HOURS, parsed, refresh_plans
from backend.contracts import require
from backend.demo import validate_text


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
    pillars = [p.strip() for p in account['profile']['pillars'].replace('，', ',').replace('\n', ',').split(',') if p.strip()] or ['常青内容']
    tasks = []
    count = account['profile']['weekly_frequency']
    for i in range(count):
        memory = memories[i] if i < len(memories) else None
        tasks.append(dict(id=str(uuid4()), date=(start+timedelta(days=(i*7)//count)).isoformat(),
            title=memory['text'] if memory else '围绕「'+pillars[i % len(pillars)]+'」准备一篇内容',
            reason='来自已接受的复盘建议；仍需实验验证' if memory else '来自账号栏目与更新频率；暂无历史效果依据',
            memory_ref=memory['id'] if memory else None, status='planned', publication_id=None))
    state['plans'].insert(0, dict(id=str(uuid4()), account_id=account['id'], week_start=start.isoformat(),
        source_type=data['source_type'], status='draft', created_at=created_at,
        goal=account['profile']['goal'] or '先完成首轮内容记录与复盘', profile_revision=account['revision'],
        memory_refs=[m['id'] for m in memories], tasks=tasks,
        limitation='计划是可撤销的建议；不会自动创作、批准或发布。'))


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

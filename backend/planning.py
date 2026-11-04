"""Account-scoped weekly plans and due reviews. No background publishing or model calls."""
from datetime import date, timedelta, datetime, timezone
from uuid import uuid4

from backend.accounts import find_account
from backend.analytics import latest_metrics, window_quality, WINDOW_HOURS, parsed, refresh_plans
from backend.contracts import require
from backend.demo import validate_text


def _items(value):
    return [part.strip() for part in value.replace('，', ',').replace('、', ',').replace('\n', ',').split(',') if part.strip()]


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
    resource_prefix = ''
    if any('少于 2 小时' in item or '少于2小时' in item for item in resources):
        resource_prefix = '轻量制作，'
    elif any('2–4 小时' in item or '2-4 小时' in item for item in resources):
        resource_prefix = '控制制作量，'
    if any('已有可用照片或视频素材' in item for item in resources):
        resource_prefix += '优先用已拍素材，'
    if any('主要用手机拍摄' in item for item in resources):
        resource_prefix += '手机可完成，'
    return f'围绕「{pillar}」{resource_prefix}{action}'


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
        title = _goal_action(goal, pillar, resources)
        if memory:
            title += f'；检验复盘建议：{memory["text"]}'
        reason = f'根据运营目标「{goal}」与内容栏目「{pillar}」安排；'
        reason += f'制作时考虑：{"、".join(resources)}。' if resources else '尚未填写时间 / 素材条件，可按实际情况调整。'
        reason += '计划是待确认的建议，不代表效果保证。'
        if memory:
            reason += '同时参考已接受的复盘建议，仍需再次验证。'
        else:
            reason += '暂无历史效果依据。'
        tasks.append(dict(id=str(uuid4()), date=(start+timedelta(days=(i*7)//count)).isoformat(),
            title=title, reason=reason,
            memory_ref=memory['id'] if memory else None, status='planned', publication_id=None))
    state['plans'].insert(0, dict(id=str(uuid4()), account_id=account['id'], week_start=start.isoformat(),
        source_type=data['source_type'], status='draft', created_at=created_at,
        goal=goal, profile_revision=account['revision'],
        profile_snapshot={k: profile[k] for k in ('positioning','pillars','goal','resources','weekly_frequency')},
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


# Content planning is independent of the account-scoped weekly planner above.
def plan(requirements, modules, budget, *, redundancy_penalty=0.15, solver='auto'):
    """Exact selection for <=12 eligible modules; deterministic greedy above that.

    ``supported`` is an upstream evidence decision, not independent verification.
    Question/limitation modules are eligible without evidence but earn no factual
    coverage. Budget measures estimated characters, not actual output length.
    """
    import math
    import itertools
    import time
    from copy import deepcopy

    started = time.perf_counter()
    if solver not in ('auto', 'greedy'):
        raise ValueError('solver must be auto or greedy')

    def number(value, label, minimum=0):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
            raise ValueError(label + ' must be a finite nonnegative number')
        return float(value)

    budget = number(budget, 'budget')
    penalty = number(redundancy_penalty, 'redundancy_penalty')
    if not isinstance(requirements, list) or not isinstance(modules, list):
        raise ValueError('requirements and modules must be lists')
    weights = {}
    normalized = []
    for item in requirements:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'].strip() or item['id'] in weights:
            raise ValueError('requirement IDs must be unique nonempty strings')
        weights[item['id']] = number(item.get('weight', 1), 'weight')
    excluded = []
    seen = set()
    for item in modules:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'].strip() or item['id'] in seen:
            raise ValueError('module IDs must be unique nonempty strings')
        seen.add(item['id'])
        length = number(item.get('length'), 'module length')
        if length <= 0:
            raise ValueError('module length must be positive')
        covers = item.get('covers', [])
        source_ids = item.get('source_ids', [])
        if not isinstance(covers, list) or not all(isinstance(v, str) for v in covers):
            raise ValueError('covers must be string IDs')
        if not isinstance(source_ids, list) or not all(isinstance(v, str) and v.strip() for v in source_ids):
            raise ValueError('source_ids must be nonempty string IDs')
        unknown = sorted(set(covers) - weights.keys())
        if unknown:
            excluded.append({'id': item['id'], 'reason': 'unknown_requirements', 'requirement_ids': unknown})
            continue
        statement_type = item.get('statement_type', 'assertion')
        if statement_type not in ('assertion', 'question', 'limitation'):
            raise ValueError('unknown statement_type')
        supported = item.get('supported') is True and bool(source_ids)
        if statement_type == 'assertion' and not supported:
            excluded.append({'id': item['id'], 'reason': 'unsupported_assertion'})
            continue
        normalized.append({'module': deepcopy(item), 'id': item['id'], 'length': length,
                           'covers': set(covers) if supported and statement_type == 'assertion' else set()})
    selected, steps, covered = [], [], set()
    used = 0.0
    pending = list(normalized)
    while pending:
        candidates = []
        for item in pending:
            new = item['covers'] - covered
            repeated = item['covers'] & covered
            gain = sum(weights[r] for r in sorted(new))
            redundancy = sum(weights[r] for r in sorted(repeated))
            marginal = gain - penalty * redundancy
            candidates.append({'id': item['id'], 'new_requirement_ids': sorted(new),
                'new_weight': gain, 'redundant_weight': redundancy, 'marginal_gain': marginal,
                'length': item['length'], 'score': marginal / item['length'],
                'fits_budget': used + item['length'] <= budget})
        eligible = [c for c in candidates if c['fits_budget'] and c['marginal_gain'] > 0]
        if not eligible:
            break
        best = min(eligible, key=lambda c: (-c['score'], -c['new_weight'], c['length'], c['id']))
        chosen = next(item for item in pending if item['id'] == best['id'])
        used += chosen['length']
        covered.update(chosen['covers'])
        selected.append(chosen['module'])
        steps.append({'step': len(steps) + 1, 'selected_id': chosen['id'],
                      'candidates': sorted(candidates, key=lambda c: c['id']),
                      'used_budget': used, 'remaining_budget': budget - used})
        pending.remove(chosen)
    def objective(items):
        counts = {r: sum(r in item['covers'] for item in items) for r in weights}
        return sum(weights[r] for r, count in counts.items() if count) - penalty * sum(
            weights[r] * max(0, count - 1) for r, count in counts.items())

    greedy_ids = [item['id'] for item in selected]
    greedy_items = [item for item in normalized if item['id'] in greedy_ids]
    greedy_objective = objective(greedy_items)
    exact = solver == 'auto' and len(normalized) <= 12
    best_items = greedy_items
    examined = 0
    if exact:
        # The entire admitted candidate pool is enumerated, including the empty
        # set. Tie breaks prefer fewer characters, then lexicographic IDs.
        ordered = sorted(normalized, key=lambda item: item['id'])
        best_key = (-greedy_objective, used, tuple(sorted(greedy_ids)))
        for size in range(len(ordered) + 1):
            for group in itertools.combinations(ordered, size):
                examined += 1
                length = sum(item['length'] for item in group)
                if length > budget:
                    continue
                key = (-objective(group), length, tuple(item['id'] for item in group))
                if key < best_key:
                    best_key, best_items = key, list(group)
        # Greedy order is kept when its chosen set is exact-optimal, so existing
        # decision logs stay directly useful. Otherwise use stable candidate IDs.
        if {item['id'] for item in best_items} == set(greedy_ids):
            best_items = [next(item for item in normalized if item['id'] == key) for key in greedy_ids]
        selected = [item['module'] for item in best_items]
        used = sum(item['length'] for item in best_items)
        covered = set().union(*(item['covers'] for item in best_items)) if best_items else set()
    selected_ids = {item['id'] for item in selected}
    for item in normalized:
        if item['id'] not in selected_ids:
            excluded.append({'id': item['id'], 'reason': 'budget' if used + item['length'] > budget else
                             'not_in_exact_optimum' if exact else 'no_positive_marginal_coverage'})
    final_items = [item for item in normalized if item['id'] in selected_ids]
    final_objective = objective(final_items)
    candidate_covered = set().union(*(item['covers'] for item in normalized)) if normalized else set()
    total = sum(weights.values())
    covered_weight = sum(weights[r] for r in sorted(covered))
    return {'algorithm': 'evidence-gated-budgeted-exact-v2' if exact else 'evidence-gated-budgeted-greedy-v2',
        'optimality_guaranteed': exact,
        'optimality_scope': 'current admitted candidate pool and stated estimated-length objective only' if exact else 'none; greedy heuristic',
        'global_retrieval_optimality': False, 'eligible_candidate_count': len(normalized),
        'exact_candidate_limit': 12, 'subsets_examined': examined,
        'objective_value': final_objective, 'greedy_objective': greedy_objective,
        'objective_gap_vs_greedy': final_objective - greedy_objective,
        'greedy_selected_module_ids': greedy_ids, 'steps_strategy': 'greedy_comparator',
        'candidate_recall_numerator': len(candidate_covered), 'candidate_recall_denominator': len(weights),
        'candidate_recall': len(candidate_covered) / len(weights) if weights else None,
        'elapsed_ms': (time.perf_counter() - started) * 1000,
        'selected_modules': selected, 'selected_module_ids': [m['id'] for m in selected],
        'covered_requirement_ids': sorted(covered), 'uncovered_requirement_ids': sorted(weights.keys() - covered),
        'covered_weight': covered_weight, 'total_weight': total,
        'weighted_coverage': covered_weight / total if total else None,
        'budget': budget, 'used_budget': used, 'remaining_budget': budget - used,
        'redundancy_penalty': penalty, 'steps': steps, 'excluded': excluded}

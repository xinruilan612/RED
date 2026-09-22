"""Deterministic service-promotion records and inquiry review.

This module deliberately stops before CRM, messaging, booking, or revenue
attribution.  It keeps user-confirmed service facts, publication bindings and
anonymous inquiry observations in the existing owner-scoped operations aggregate.
"""
import copy
from collections import Counter
from datetime import datetime
from urllib.parse import urlsplit
from uuid import uuid4

from backend.contracts import require
from backend.demo import validate_text


PUBLIC_FIELDS = ('offering', 'target_customer', 'delivery', 'price', 'availability', 'contact')
GOALS = ('discovery', 'trust', 'inquiry')
PROBLEM_SOURCES = ('user_provided', 'consultation_summary', 'model_hypothesis')
ATTRIBUTIONS = ('explicit', 'multi_touch', 'unknown')
VALIDITIES = ('pending', 'valid', 'invalid')
SOURCE_TYPES = ('manual', 'simulation')


def migrate(state):
    for key in ('services', 'portfolio_items', 'promotion_briefs', 'inquiries', 'promotion_analyses'):
        state.setdefault(key, [])
    publications = {row['id']: row for row in state.get('publications', [])}
    for inquiry in state['inquiries']:
        if 'source_type' not in inquiry:
            publication = publications.get(inquiry.get('publication_id'))
            inquiry['source_type'] = publication.get('provenance', 'manual') if publication else 'manual'
    inquiries = {row['id']: row for row in state['inquiries']}
    for analysis in state['promotion_analyses']:
        sources = {inquiries[identity]['source_type'] for identity in analysis.get('inquiry_refs', [])
                   if identity in inquiries}
        analysis.setdefault('source_type', sources.pop() if len(sources) == 1 else 'manual')
    return state


def _item(rows, identity, message='记录不可访问'):
    found = next((row for row in rows if row['id'] == identity), None)
    require(found is not None, 'RESOURCE_NOT_FOUND', message)
    return found


def _account(state, identity):
    return _item(state['accounts'], identity, '账号不可访问')


def _as_datetime(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _optional(value, label, maximum):
    return validate_text(value, label, maximum, True)


def _link(value):
    value = _optional(value, '作品链接', 1000)
    if not value:
        return ''
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password
    except ValueError:
        valid = False
    require(valid, 'INVALID_INPUT', '请填写有效的 http/https 作品链接')
    return value


def _snapshot_service(service):
    return {key: copy.deepcopy(service[key]) for key in ('id', 'version', 'name', 'offering', 'target_customer',
                                                          'delivery', 'price', 'availability', 'contact',
                                                          'public_fields', 'active')}


def _invalidate(state, inquiry_id=None, service_id=None):
    for analysis in state['promotion_analyses']:
        if analysis['status'] == 'valid' and ((inquiry_id and inquiry_id in analysis['inquiry_refs']) or
                                               (service_id and analysis['service_id'] == service_id)):
            analysis['status'] = 'superseded'
            analysis['invalid_reason'] = '依赖的咨询或服务资料已修改'


def save_service(state, data, now):
    required = {'id', 'account_id', 'name', 'offering', 'target_customer', 'delivery', 'price',
                'availability', 'contact', 'public_fields', 'active'}
    require(set(data) == required, 'INVALID_INPUT', '服务档案字段无效')
    account = _account(state, data['account_id'])
    require(type(data['active']) is bool, 'INVALID_INPUT', '服务状态无效')
    require(isinstance(data['public_fields'], list) and len(data['public_fields']) == len(set(data['public_fields']))
            and set(data['public_fields']) <= set(PUBLIC_FIELDS), 'INVALID_INPUT', '公开字段无效')
    values = dict(name=validate_text(data['name'], '服务名称', 100),
                  offering=validate_text(data['offering'], '具体服务', 1200),
                  target_customer=validate_text(data['target_customer'], '目标客户', 500),
                  delivery=validate_text(data['delivery'], '服务地域或方式', 500),
                  price=_optional(data['price'], '价格', 300),
                  availability=_optional(data['availability'], '可约时间', 300),
                  contact=_optional(data['contact'], '预约方式', 500))
    require(not any(row['account_id'] == account['id'] and row['id'] != data['id'] and
                    row['name'] == values['name'] and row['active'] for row in state['services']),
            'DUPLICATE', '当前账号已有同名服务')
    if data['id']:
        service = _item(state['services'], data['id'], '服务档案不可访问')
        require(service['account_id'] == account['id'], 'RESOURCE_NOT_FOUND', '服务档案不可访问')
        service['revisions'].append(_snapshot_service(service) | {'updated_at': service['updated_at']})
        service.update(values, public_fields=list(data['public_fields']), active=data['active'],
                       version=service['version'] + 1, updated_at=now)
        for brief in state['promotion_briefs']:
            if brief['service_id'] == service['id'] and brief['status'] == 'active':
                brief['status'] = 'needs_review'
                brief['invalid_reason'] = '服务档案已更新，请重新生成推广简报'
        _invalidate(state, service_id=service['id'])
        return service
    service = dict(id=str(uuid4()), account_id=account['id'], platform=account['platform'], version=1,
                   public_fields=list(data['public_fields']), active=data['active'], revisions=[],
                   created_at=now, updated_at=now, **values)
    state['services'].append(service)
    return service


def save_portfolio(state, data, now):
    required = {'id', 'service_id', 'title', 'description', 'role', 'facts', 'link', 'public_confirmed', 'active'}
    require(set(data) == required, 'INVALID_INPUT', '作品记录字段无效')
    service = _item(state['services'], data['service_id'], '服务档案不可访问')
    require(type(data['public_confirmed']) is bool and type(data['active']) is bool,
            'INVALID_INPUT', '作品公开状态无效')
    values = dict(title=validate_text(data['title'], '作品标题', 120),
                  description=validate_text(data['description'], '作品描述', 1500),
                  role=validate_text(data['role'], '本人承担工作', 500),
                  facts=validate_text(data['facts'], '可支持事实', 1500),
                  link=_link(data['link']))
    if data['id']:
        item = _item(state['portfolio_items'], data['id'], '作品记录不可访问')
        require(item['service_id'] == service['id'], 'RESOURCE_NOT_FOUND', '作品记录不可访问')
        item['revisions'].append({k: copy.deepcopy(item[k]) for k in ('version', 'title', 'description', 'role',
            'facts', 'link', 'public_confirmed', 'active', 'updated_at')})
        item.update(values, public_confirmed=data['public_confirmed'], active=data['active'],
                    version=item['version'] + 1, updated_at=now)
        for brief in state['promotion_briefs']:
            if item['id'] in brief['portfolio_ids'] and brief['status'] == 'active':
                brief['status'] = 'needs_review'
                brief['invalid_reason'] = '引用作品已更新，请重新生成推广简报'
        return item
    item = dict(id=str(uuid4()), account_id=service['account_id'], service_id=service['id'], version=1,
                public_confirmed=data['public_confirmed'], active=data['active'], revisions=[],
                created_at=now, updated_at=now, **values)
    state['portfolio_items'].append(item)
    return item


def create_brief(state, data, now):
    require(set(data) == {'account_id', 'service_id', 'goal', 'customer_problem', 'problem_source', 'portfolio_ids'},
            'INVALID_INPUT', '推广简报字段无效')
    account = _account(state, data['account_id'])
    service = _item(state['services'], data['service_id'], '服务档案不可访问')
    require(service['account_id'] == account['id'] and service['active'], 'INVALID_TRANSITION', '服务已停用或不属于当前账号')
    require(data['goal'] in GOALS and data['problem_source'] in PROBLEM_SOURCES, 'INVALID_INPUT', '推广目标或问题来源无效')
    require(isinstance(data['portfolio_ids'], list) and len(data['portfolio_ids']) <= 10 and
            len(data['portfolio_ids']) == len(set(data['portfolio_ids'])), 'INVALID_INPUT', '作品选择无效')
    problem = validate_text(data['customer_problem'], '客户问题', 500)
    required_public = {'offering', 'target_customer', 'delivery'}
    require(required_public <= set(service['public_fields']), 'INVALID_TRANSITION', '请先允许公开具体服务、目标客户和服务地域/方式')
    portfolio = []
    for identity in data['portfolio_ids']:
        row = _item(state['portfolio_items'], identity, '作品记录不可访问')
        require(row['service_id'] == service['id'] and row['active'] and row['public_confirmed'],
                'INVALID_TRANSITION', '所选作品未确认公开、已停用或不属于此服务')
        portfolio.append({k: copy.deepcopy(row[k]) for k in ('id', 'version', 'title', 'description', 'role', 'facts', 'link')})
    public = {'name': service['name']} | {key: service[key] for key in service['public_fields']}
    goal_labels = {'discovery': '被发现', 'trust': '建立信任', 'inquiry': '促成咨询'}
    source_labels = {'user_provided': '用户提供', 'consultation_summary': '真实咨询汇总', 'model_hypothesis': '待验证假设'}
    topic = f"{service['name']}｜{problem}"[:100]
    facts = [f"服务：{public.get('offering', '')}", f"适合：{public.get('target_customer', '')}",
             f"服务方式：{public.get('delivery', '')}"]
    for key, label in (('price', '价格'), ('availability', '可约时间'), ('contact', '预约方式')):
        if public.get(key):
            facts.append(f'{label}：{public[key]}')
    facts += [f"作品《{row['title']}》：{row['facts']}（本人负责：{row['role']}）" for row in portfolio]
    missing = []
    if not portfolio:
        missing.append('暂无确认可公开的作品；正文不能虚构案例或客户评价')
    if 'price' not in service['public_fields'] or not service['price']:
        missing.append('价格未公开；正文不得生成具体报价')
    if 'availability' not in service['public_fields'] or not service['availability']:
        missing.append('档期未公开；正文不得承诺可预约时间')
    brief = dict(id=str(uuid4()), account_id=account['id'], service_id=service['id'],
                 service_version=service['version'], portfolio_ids=[row['id'] for row in portfolio],
                 portfolio_versions={row['id']: row['version'] for row in portfolio}, goal=data['goal'],
                 goal_label=goal_labels[data['goal']], customer_problem=problem,
                 problem_source=data['problem_source'], problem_source_label=source_labels[data['problem_source']],
                 topic=topic, audience=service['target_customer'], public_service=public, portfolio=portfolio,
                 material='\n'.join(facts), missing=missing, status='active', invalid_reason='', created_at=now)
    state['promotion_briefs'].insert(0, brief)
    return brief


def brief_context(state, account_id, brief_id):
    brief = _item(state['promotion_briefs'], brief_id, '推广简报不可访问')
    require(brief['account_id'] == account_id and brief['status'] == 'active', 'INVALID_TRANSITION', '推广简报已失效或不属于当前账号')
    service = _item(state['services'], brief['service_id'], '服务档案不可访问')
    require(service['active'] and service['version'] == brief['service_version'], 'VERSION_CONFLICT', '服务档案已变化，请重新生成推广简报')
    for identity, version in brief['portfolio_versions'].items():
        row = _item(state['portfolio_items'], identity, '作品记录不可访问')
        require(row['active'] and row['public_confirmed'] and row['version'] == version,
                'VERSION_CONFLICT', '作品公开状态或版本已变化，请重新生成推广简报')
    return copy.deepcopy(brief)


def record_inquiry(state, data, now, parse_timestamp):
    required = {'event_key', 'service_id', 'publication_id', 'occurred_at', 'problem_category',
                'summary', 'attribution', 'attribution_basis', 'validity', 'source_type'}
    require(set(data) == required, 'INVALID_INPUT', '咨询记录字段无效')
    key = validate_text(data['event_key'], '咨询幂等标识', 100)
    require(not any(row['event_key'] == key for row in state['inquiries']), 'DUPLICATE', '这次咨询已经记录')
    service = _item(state['services'], data['service_id'], '服务档案不可访问')
    require(data['attribution'] in ATTRIBUTIONS and data['validity'] in VALIDITIES,
            'INVALID_INPUT', '归因或有效性状态无效')
    require(data['source_type'] in SOURCE_TYPES, 'INVALID_INPUT', '咨询数据来源无效')
    publication_id = data['publication_id'] or None
    if data['attribution'] == 'explicit':
        require(publication_id, 'INVALID_INPUT', '明确关联需要选择已发布内容')
    else:
        require(publication_id is None, 'INVALID_INPUT', '多触点或来源未知不强行绑定单篇内容')
    if publication_id:
        publication = _item(state['publications'], publication_id, '发布记录不可访问')
        promotion = publication.get('promotion') or {}
        require(publication['account_id'] == service['account_id'] and promotion.get('service_id') == service['id']
                and publication['status'] in ('SIMULATED', 'MANUAL_REPORTED'),
                'INVALID_TRANSITION', '只能关联同一服务场景的已发布记录')
        require(publication['provenance'] == data['source_type'], 'INVALID_TRANSITION',
                '咨询数据来源必须与关联发布记录一致')
    row = dict(id=str(uuid4()), event_key=key, account_id=service['account_id'], service_id=service['id'],
               publication_id=publication_id, occurred_at=parse_timestamp(data['occurred_at']),
               problem_category=validate_text(data['problem_category'], '问题分类', 100),
               summary=_optional(data['summary'], '脱敏摘要', 1000), attribution=data['attribution'],
               attribution_basis=_optional(data['attribution_basis'], '归因依据', 500), validity=data['validity'],
               source_type=data['source_type'],
               version=1, status='active', created_at=now, updated_at=now,
               limitation='用户人工报告的匿名咨询，不是平台认证、成交或收入证明')
    state['inquiries'].insert(0, row)
    return row


def update_inquiry(state, data, now):
    require(set(data) == {'id', 'validity', 'status'}, 'INVALID_INPUT', '咨询更新字段无效')
    row = _item(state['inquiries'], data['id'], '咨询记录不可访问')
    require(data['validity'] in VALIDITIES and data['status'] in ('active', 'revoked'),
            'INVALID_INPUT', '咨询状态无效')
    require(row['status'] == 'active', 'INVALID_TRANSITION', '已撤销咨询不能再次修改')
    row.update(validity=data['validity'], status=data['status'], version=row['version'] + 1, updated_at=now)
    _invalidate(state, inquiry_id=row['id'])
    return row


def analyze(state, data, now, parse_timestamp):
    require(set(data) == {'account_id', 'service_id', 'source_type', 'window_start', 'window_end',
                          'confirmed_complete', 'zero_confirmed'},
            'INVALID_INPUT', '推广复盘字段无效')
    account = _account(state, data['account_id'])
    service = _item(state['services'], data['service_id'], '服务档案不可访问')
    require(service['account_id'] == account['id'], 'RESOURCE_NOT_FOUND', '服务档案不可访问')
    require(type(data['confirmed_complete']) is bool and type(data['zero_confirmed']) is bool,
            'INVALID_INPUT', '窗口确认状态无效')
    require(data['source_type'] in SOURCE_TYPES, 'INVALID_INPUT', '复盘数据来源无效')
    start, end = parse_timestamp(data['window_start']), parse_timestamp(data['window_end'])
    start_dt, end_dt = _as_datetime(start), _as_datetime(end)
    require(start_dt < end_dt,
            'INVALID_INPUT', '观察窗口起止无效')
    rows = [row for row in state['inquiries'] if row['service_id'] == service['id'] and row['status'] == 'active'
            and row['source_type'] == data['source_type']
            and start_dt <= _as_datetime(row['occurred_at']) <= end_dt]
    require(not data['zero_confirmed'] or (data['confirmed_complete'] and not rows),
            'INVALID_INPUT', '只有完整回填且确实无记录时才能确认零咨询')
    explicit = sum(row['attribution'] == 'explicit' for row in rows)
    valid = sum(row['validity'] == 'valid' for row in rows)
    unknown = sum(row['attribution'] == 'unknown' for row in rows)
    multi = sum(row['attribution'] == 'multi_touch' for row in rows)
    top = Counter(row['problem_category'] for row in rows).most_common(3)
    if top:
        suggestion = f"咨询中反复出现“{top[0][0]}”，下一篇可先说明这一问题，并继续记录同口径反馈。"
    elif data['zero_confirmed']:
        suggestion = '本窗口已明确确认无咨询；可优先检查服务说明、作品证据和行动引导是否清楚，再做一次可控测试。'
    else:
        suggestion = '反馈尚未完整回填，先补充咨询记录；缺失不能当作零咨询。'
    analysis = dict(id=str(uuid4()), account_id=account['id'], service_id=service['id'],
                    service_version=service['version'], window_start=start, window_end=end,
                    source_type=data['source_type'],
                    confirmed_complete=data['confirmed_complete'], zero_confirmed=data['zero_confirmed'],
                    inquiry_refs=[row['id'] for row in rows], inquiry_versions={row['id']: row['version'] for row in rows},
                    counts=dict(total=len(rows), explicit=explicit, valid=valid, unknown=unknown, multi_touch=multi),
                    repeated_questions=[{'category': name, 'count': count} for name, count in top],
                    suggestion=suggestion, status='valid', invalid_reason='', created_at=now,
                    limitation='仅汇总用户人工回填，不推断因果、成交、收入或稳定增长规律')
    state['promotion_analyses'].insert(0, analysis)
    return analysis

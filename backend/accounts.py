"""Versioned local account identity and preference history; no platform OAuth."""
import copy
import json
from datetime import datetime, timezone
from uuid import uuid4, uuid5, NAMESPACE_URL

from backend.contracts import require
from backend.demo import validate_text

PROFILE_FIELDS = ('positioning', 'audience', 'tone', 'pillars', 'goal', 'resources', 'banned')


def account_id(owner, platform, name):
    return str(uuid5(NAMESPACE_URL, json.dumps([owner, platform, name], ensure_ascii=False)))


def new_account(identity, name, platform):
    return dict(id=identity, name=name, platform=platform, aliases=[name], revision=1,
                profile={**{k: '' for k in PROFILE_FIELDS}, 'weekly_frequency': 3}, revisions=[])


def migrate(state, owner):
    """Deterministic read adapter; persisted in the next transaction, never loses v0.4 records."""
    state.setdefault('accounts', [])
    for key in ('preferences', 'analyses', 'plans', 'competitors', 'signals', 'hypotheses'):
        state.setdefault(key, [])
    state.setdefault('trials_schema_version', 1)
    pairs = [('xiaohongshu', '我的账号')]
    pairs += [(p['platform'], p['account']) for p in state['publications'] if not p.get('account_id')]
    for platform, name in pairs:
        identity = account_id(owner, platform, name)
        if not any(a['id'] == identity or (a['platform'] == platform and name in a['aliases']) for a in state['accounts']):
            state['accounts'].append(new_account(identity, name, platform))
    for key in ('publications', 'metrics', 'memories'):
        for record in state[key]:
            if not record.get('account_id'):
                account = next((a for a in state['accounts'] if a['platform'] == record['platform'] and record['account'] in a['aliases']), None)
                if account:
                    record['account_id'] = account['id']
            if key == 'publications':
                record.setdefault('format', 'video' if record['platform'] == 'douyin' else 'image_text')
                record.setdefault('pillar', '未分类')
                record.setdefault('traffic', 'unknown')
                record.setdefault('provenance', 'simulation' if record['mode'] == 'simulation' else 'manual')
    state['operations_schema_version'] = 2
    return state


def find_account(state, identity):
    account = next((a for a in state['accounts'] if a['id'] == identity), None)
    require(account is not None, 'RESOURCE_NOT_FOUND', '账号不可访问')
    return account


def save_account(state, data):
    require(set(data) == {'id', 'name', 'platform', 'profile'}, 'INVALID_INPUT', '账号字段无效')
    require(data['platform'] in ('xiaohongshu', 'douyin'), 'INVALID_INPUT', '平台无效')
    name = validate_text(data['name'], '账号名称', 80)
    profile = data['profile']
    require(isinstance(profile, dict) and set(profile) == set(PROFILE_FIELDS) | {'weekly_frequency'}, 'INVALID_INPUT', '档案字段无效')
    profile = {k: validate_text(profile[k], k, 800, True) for k in PROFILE_FIELDS} | {'weekly_frequency': profile['weekly_frequency']}
    require(type(profile['weekly_frequency']) is int and 1 <= profile['weekly_frequency'] <= 7, 'INVALID_INPUT', '每周计划为 1 至 7 篇')
    require(not any(a['id'] != data['id'] and a['platform'] == data['platform'] and name in a['aliases'] for a in state['accounts']), 'DUPLICATE', '该平台已有同名账号')
    if data['id']:
        account = find_account(state, data['id'])
        require(account['platform'] == data['platform'], 'INVALID_INPUT', '已有账号不能更换平台，请新建账号')
        if account['name'] == name and account['profile'] == profile:
            return
        account['revisions'].append(dict(revision=account['revision'], name=account['name'], profile=copy.deepcopy(account['profile'])))
        account['revision'] += 1
        account.update(name=name, profile=profile)
        if name not in account['aliases']:
            account['aliases'].append(name)
    else:
        account = new_account(str(uuid4()), name, data['platform'])
        account['profile'] = profile
        state['accounts'].append(account)


def capture_edit(db, run, before):
    """Save edits in the same transaction as the new draft; retries never duplicate events."""
    if not db.has_table('operations'):
        return
    op = run.context.get('operations', {})
    identity = op.get('account_id')
    if not identity:
        return
    row = db.execute('SELECT payload FROM operations WHERE owner=?', (run.owner_id,)).fetchone()
    if row is None:
        from backend.operations import seed
        state = migrate(seed(), run.owner_id)
    else:
        state = migrate(json.loads(row[0]), run.owner_id)
    find_account(state, identity)
    after = run.drafts[-1]
    changes = {k: {'before': before['content'][k], 'after': after['content'][k]}
               for k in before['content'] if before['content'][k] != after['content'][k]}
    if not changes:
        return
    state['preferences'].append(dict(id=str(uuid4()), account_id=identity, run_id=run.run_id,
        before_ref=before['ref'], after_ref=after['ref'], changes=changes, source_type='user_edit',
        mode=run.context.get('mode', 'simulation'), created_at=datetime.now(timezone.utc).isoformat(),
        interpretation='用户表达偏好信号，不代表传播效果；仅记录，不自动写成永久规则'))
    state['version'] += 1
    db.execute('INSERT INTO operations VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET payload=excluded.payload', (run.owner_id, json.dumps(state, ensure_ascii=False)))
    from backend.database import project_operations
    project_operations(db, run.owner_id, state)

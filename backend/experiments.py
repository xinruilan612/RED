"""Explainable exploration/exploitation decisions for account content experiments."""
from math import log, sqrt
from uuid import uuid4

from backend.accounts import find_account
from backend.analytics import latest_metrics, window_quality
from backend.contracts import require

ALGORITHM = 'content-ucb1-v1'
EXPLORATION_WEIGHT = 8.0
ACTION_WEIGHTS = {'likes': 1, 'saves': 3, 'comments': 2, 'shares': 3}


def pillars(account, posts):
    configured = account['profile']['pillars'].replace('，', ',').replace('\n', ',').split(',')
    values = [value.strip() for value in configured if value.strip()]
    values += [post['pillar'] for post in posts if post.get('pillar') not in (None, '', '未分类')]
    return list(dict.fromkeys(values)) or ['常青内容']


def reward(metric):
    values = metric['values']; views = values.get('views')
    if not views or any(values.get(field) is None for field in ACTION_WEIGHTS):
        return None
    weighted = sum(values[field] * weight for field, weight in ACTION_WEIGHTS.items())
    return round(weighted / views * 1000, 3)


def recommend(state, account_id, source_type, window, created_at):
    """Return a deterministic UCB1 recommendation with an inspectable evidence ledger."""
    require(source_type in ('manual', 'simulation'), 'INVALID_INPUT', '实验数据来源无效')
    require(window in ('24h', '72h', '7d'), 'INVALID_INPUT', '实验观察窗口无效')
    account = find_account(state, account_id)
    posts = [post for post in state['publications'] if post.get('account_id') == account_id
             and post.get('provenance') == source_type]
    candidates = pillars(account, posts)
    by_id = {post['id']: post for post in posts}
    samples = {name: [] for name in candidates}; excluded = []
    for metric in latest_metrics(state).values():
        post = by_id.get(metric['publication_id'])
        if not post or metric['window'] != window:
            continue
        reasons = []
        if post.get('pillar') not in samples: reasons.append('栏目未列入候选')
        if post.get('traffic') != 'organic': reasons.append('非自然流量或流量类型未知')
        if window_quality(post, metric)[0] != 'comparable': reasons.append('观察时间不可比')
        value = reward(metric)
        if value is None: reasons.append('阅读/播放或互动指标不完整')
        if reasons:
            excluded.append({'publication_id': post['id'], 'metric_id': metric['id'], 'reasons': reasons})
        else:
            samples[post['pillar']].append((metric, value))
    total = sum(len(rows) for rows in samples.values())
    scored = []
    for order, name in enumerate(candidates):
        rows = samples[name]
        mean = round(sum(value for _, value in rows) / len(rows), 3) if rows else None
        bonus = round(EXPLORATION_WEIGHT * sqrt(log(total + 1) / len(rows)), 3) if rows and total else None
        score = round(mean + bonus, 3) if mean is not None else None
        scored.append({'pillar': name, 'samples': len(rows), 'mean_reward': mean,
                       'exploration_bonus': bonus, 'ucb_score': score,
                       'metric_refs': [metric['id'] for metric, _ in rows], '_order': order})
    untested = [row for row in scored if row['samples'] == 0]
    chosen = (untested[0] if untested else max(scored, key=lambda row: (row['ucb_score'], -row['_order'])))
    tested = [row for row in scored if row['samples']]
    best_mean = max(tested, key=lambda row: row['mean_reward']) if tested else None
    mode = 'explore' if chosen['samples'] == 0 or (best_mean and chosen['pillar'] != best_mean['pillar']) else 'exploit'
    confidence = 'insufficient' if total < 3 else 'low' if chosen['samples'] < 3 else 'medium'
    for row in scored: row.pop('_order')
    evidence = sorted({ref for row in scored for ref in row['metric_refs']})
    return {'id': str(uuid4()), 'account_id': account_id, 'platform': account['platform'],
            'source_type': source_type, 'window': window, 'status': 'proposed', 'created_at': created_at,
            'algorithm': ALGORITHM, 'decision_mode': mode, 'confidence': confidence,
            'chosen_pillar': chosen['pillar'],
            'hypothesis': f"下一篇围绕「{chosen['pillar']}」创作，只改变一个表达变量，并在 {window} 后按同口径记录。",
            'control': '保持账号、平台、内容形式、流量类型和观察窗口一致',
            'variant': '只改变开头表达；其余主要条件保持不变',
            'primary_metric': '每千次阅读/播放加权有效互动',
            'reward_formula': '1000 × (点赞×1 + 收藏×3 + 评论×2 + 分享×3) ÷ 阅读/播放',
            'sample_size': total, 'candidates': scored, 'metric_refs': evidence, 'excluded': excluded,
            'limitations': ['UCB1 在已有策略利用与低样本策略探索之间做决策，不预测爆款。',
                            '权重是可审计的产品策略，不代表平台官方价值或因果贡献。',
                            '人工录入和导入记录未由平台独立核实；一次只改变一个变量仍需用户执行。']}


def invalidate_experiments(state, obsolete_metric_ids):
    for experiment in state.get('experiments', []):
        if experiment['status'] not in ('rejected', 'revoked', 'superseded') and set(experiment['metric_refs']) & obsolete_metric_ids:
            experiment['status'] = 'superseded'

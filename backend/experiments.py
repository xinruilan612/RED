"""Explainable exploration/exploitation decisions for account content experiments."""
import copy
from math import log, sqrt
from uuid import uuid4

from backend.accounts import find_account
from backend.analytics import latest_metrics, window_quality
from backend.contracts import require
from backend.workflow import digest

ALGORITHM = 'content-ucb1-v2'
EXPLORATION_WEIGHT = 8.0
ACTION_WEIGHTS = {'likes': 1, 'saves': 3, 'comments': 2, 'shares': 3}
FORMATS = ('image_text', 'video')
DECISION_FIELDS = ('id', 'schema_version', 'account_id', 'platform', 'format', 'source_type', 'window',
                   'created_at', 'algorithm', 'decision_mode', 'confidence', 'chosen_pillar',
                   'hypothesis', 'control', 'variant', 'primary_metric', 'reward_formula',
                   'sample_size', 'candidates', 'metric_refs', 'dependency_metric_refs',
                   'excluded', 'evidence', 'baseline_reward', 'baseline_metric_refs', 'limitations')


def default_format(platform):
    return 'video' if platform == 'douyin' else 'image_text'


def decision_snapshot(experiment):
    return {key: copy.deepcopy(experiment.get(key)) for key in DECISION_FIELDS}


def active_experiment(state, identity, account_id, platform, source_type, content_format, snapshot=None):
    """Only server-owned accepted decisions can authorize a new use or publish."""
    experiment = next((row for row in state['experiments'] if row['id'] == identity), None)
    require(experiment is not None, 'RESOURCE_NOT_FOUND', '实验不可访问')
    require(experiment['status'] == 'accepted', 'INVALID_TRANSITION', '实验未接受、已撤销或依据已失效')
    require(experiment.get('schema_version') == 2 and experiment.get('decision_hash'),
            'INVALID_TRANSITION', '旧实验缺少形式和证据快照，请重新生成建议')
    require((experiment['account_id'], experiment['platform'], experiment['source_type'], experiment['format']) ==
            (account_id, platform, source_type, content_format), 'INVALID_INPUT', '实验账号、平台、来源或内容形式不一致')
    expected = digest(decision_snapshot(experiment))
    require(experiment['decision_hash'] == expected, 'VERSION_CONFLICT', '实验依据快照不完整，请重新生成')
    if snapshot is not None:
        require(isinstance(snapshot, dict) and snapshot.get('decision_hash') == expected and
                digest(decision_snapshot(snapshot)) == expected,
                'VERSION_CONFLICT', '任务中的实验快照与服务端依据不一致')
    return experiment


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


def recommend(state, account_id, source_type, window, created_at, content_format=None, platform=None):
    """Return a deterministic UCB1 recommendation with an inspectable evidence ledger."""
    require(source_type in ('manual', 'simulation'), 'INVALID_INPUT', '实验数据来源无效')
    require(window in ('24h', '72h', '7d'), 'INVALID_INPUT', '实验观察窗口无效')
    account = find_account(state, account_id)
    require(platform is None or platform == account['platform'], 'INVALID_INPUT', '推荐平台与账号不一致')
    content_format = default_format(account['platform']) if content_format is None else content_format
    require(content_format in FORMATS, 'INVALID_INPUT', '实验内容形式无效')
    posts = [post for post in state['publications'] if post.get('account_id') == account_id]
    candidates = pillars(account, [post for post in posts if post.get('platform') == account['platform']
                                  and post.get('provenance') == source_type and post.get('format') == content_format])
    by_id = {post['id']: post for post in posts}
    samples = {name: [] for name in candidates}; excluded = []; evidence = []
    for metric in latest_metrics(state).values():
        post = by_id.get(metric['publication_id'])
        if not post:
            continue
        reasons = []
        if post.get('platform') != account['platform'] or metric.get('platform') != account['platform']:
            reasons.append('平台不一致')
        if post.get('provenance') != source_type or metric.get('source_type') != source_type:
            reasons.append('数据来源不一致')
        if metric.get('account_id') != account_id: reasons.append('指标账号不一致')
        if post.get('format') != content_format: reasons.append('内容形式不一致')
        if metric['window'] != window: reasons.append('观察窗口不一致')
        if post.get('pillar') not in samples: reasons.append('栏目未列入候选')
        if post.get('traffic') != 'organic': reasons.append('非自然流量或流量类型未知')
        if not post.get('published_at') or post.get('status') not in ('SIMULATED', 'MANUAL_REPORTED'):
            reasons.append('尚未发布')
        elif window_quality(post, metric)[0] != 'comparable': reasons.append('观察时间不可比')
        value = reward(metric)
        if value is None: reasons.append('阅读/播放或互动指标不完整')
        if reasons:
            excluded.append({'publication_id': post['id'], 'metric_id': metric['id'], 'reasons': reasons})
        else:
            samples[post['pillar']].append((metric, value))
            evidence.append(dict(publication_id=post['id'], metric_id=metric['id'], revision=metric['revision'],
                                 observed_at=metric['observed_at'], values=copy.deepcopy(metric['values']),
                                 pillar=post['pillar'], format=post['format'], traffic=post['traffic'], reward=value))
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
    scored_refs = sorted({ref for row in scored for ref in row['metric_refs']})
    packet = {'id': str(uuid4()), 'schema_version': 2, 'account_id': account_id, 'platform': account['platform'],
            'format': content_format, 'publication_id': None, 'invalid_reason': '',
            'source_type': source_type, 'window': window, 'status': 'proposed', 'created_at': created_at,
            'algorithm': ALGORITHM, 'decision_mode': mode, 'confidence': confidence,
            'chosen_pillar': chosen['pillar'],
            'hypothesis': f"下一篇围绕「{chosen['pillar']}」创作，只改变一个表达变量，并在 {window} 后按同口径记录。",
            'control': '保持账号、平台、内容形式、流量类型和观察窗口一致',
            'variant': '只改变开头表达；其余主要条件保持不变',
            'primary_metric': '每千次阅读/播放加权有效互动',
            'reward_formula': '1000 × (点赞×1 + 收藏×3 + 评论×2 + 分享×3) ÷ 阅读/播放',
            'sample_size': total, 'candidates': scored, 'metric_refs': scored_refs, 'excluded': excluded,
            'dependency_metric_refs': sorted(set(scored_refs) | {row['metric_id'] for row in excluded}),
            'evidence': evidence, 'baseline_reward': chosen['mean_reward'],
            'baseline_metric_refs': list(chosen['metric_refs']),
            'limitations': ['UCB1 在已有策略利用与低样本策略探索之间做决策，不预测爆款。',
                            '权重是可审计的产品策略，不代表平台官方价值或因果贡献。',
                            '人工录入和导入记录未由平台独立核实；一次只改变一个变量仍需用户执行。']}
    packet['decision_hash'] = digest(decision_snapshot(packet))
    return packet


def invalidate_experiments(state, obsolete_metric_ids):
    invalid = set()
    for experiment in state.get('experiments', []):
        refs = set(experiment.get('dependency_metric_refs', experiment['metric_refs']))
        if experiment['status'] not in ('rejected', 'revoked', 'superseded') and refs & obsolete_metric_ids:
            experiment['status'] = 'superseded'
            experiment['invalid_reason'] = '推荐时计分或排除的依据已修正，请生成新实验；旧快照保留审计'
            invalid.add(experiment['id'])
    for result in state.get('experiment_results', []):
        if result['experiment_id'] in invalid and result['status'] != 'superseded':
            result['status'] = 'superseded'
            result['invalid_reason'] = '实验推荐依据已修正'

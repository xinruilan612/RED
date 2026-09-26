"""Independent, deterministic analytics agent. No model scores or causal claims."""
from datetime import datetime
from statistics import median
from uuid import uuid4

from backend.contracts import require, CONTRACT

POLICY = CONTRACT['operations_extension']
WINDOW_HOURS = POLICY['windows_hours']
RATE_FIELDS = {'saves': '收藏', 'likes': '点赞', 'comments': '评论', 'shares': '分享',
               'new_followers': '作品归因关注', 'completed_plays': '完整播放'}


def parsed(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def window_quality(post, metric):
    hours = (parsed(metric['observed_at']) - parsed(post['published_at'])).total_seconds() / 3600
    target = WINDOW_HOURS[metric['window']]
    return ('early' if hours < target else 'late' if hours > target * (1 + POLICY['window_late_tolerance']) else 'comparable'), round(hours, 2)


def rates(metric):
    values = metric['values']; views = values.get('views')
    result = {k: round(values[k] / views * 1000, 3) if views and values.get(k) is not None else None for k in RATE_FIELDS}
    fields = ('likes', 'saves', 'comments', 'shares')
    result['interaction'] = round(sum(values[k] for k in fields) / views * 1000, 3) if views and all(values.get(k) is not None for k in fields) else None
    return result


def latest_metrics(state):
    result = {}
    for metric in state['metrics']:
        result[(metric['publication_id'], metric['window'])] = metric
    return result


class AnalyticsAgent:
    agent_id = 'analytics'
    version = 'rules-1.0'

    def run(self, state, metric, created_at):
        posts = {p['id']: p for p in state['publications']}
        post = posts[metric['publication_id']]
        latest = latest_metrics(state)
        require(latest[(post['id'], metric['window'])]['id'] == metric['id'], 'INVALID_TRANSITION', '只能分析最新快照')
        quality, hours = window_quality(post, metric)
        flags = []
        if quality != 'comparable': flags.append('观察时间偏早' if quality == 'early' else '观察时间超出窗口容差')
        if post['traffic'] == 'unknown': flags.append('流量类型未知，无法建立可比基线')
        if not metric['values'].get('views'): flags.append('缺少非零阅读/播放分母，不能计算比例')
        peers = []; excluded = []
        for candidate in latest.values():
            other = posts[candidate['publication_id']]
            if other['id'] == post['id'] or other.get('account_id') != post.get('account_id'):
                continue
            reasons = []
            for field in ('platform', 'format', 'traffic', 'provenance'):
                if other[field] != post[field]: reasons.append(field+'不一致')
            if candidate['window'] != metric['window']: reasons.append('观察窗口不一致')
            if parsed(other['published_at']) >= parsed(post['published_at']): reasons.append('不是此前发布的作品')
            if parsed(candidate['observed_at']) > parsed(metric['observed_at']): reasons.append('该数据当时尚未观测')
            if window_quality(other, candidate)[0] != 'comparable': reasons.append('实际观察时长不在窗口容差内')
            if reasons:
                excluded.append({'metric_id': candidate['id'], 'reasons': reasons})
            elif quality == 'comparable' and post['traffic'] != 'unknown':
                peers.append(candidate)
        current = rates(metric)
        comparisons = {}
        for field, value in current.items():
            valid = [(m, rates(m)[field]) for m in peers if rates(m)[field] is not None]
            baseline = median([v for _, v in valid]) if len(valid) >= POLICY['baseline_display_min'] else None
            comparisons[field] = dict(current=value, baseline=baseline, sample_size=len(valid),
                difference=round(value-baseline, 3) if value is not None and baseline is not None else None,
                metric_refs=[m['id'] for m, _ in valid])
        observations = []
        for field, label in RATE_FIELDS.items():
            result = comparisons[field]
            if result['current'] is not None:
                text = f"每千次{'播放' if post['format'] == 'video' else '阅读'}的{label}为 {result['current']}"
                if result['baseline'] is not None:
                    text += f"；此前 {result['sample_size']} 篇可比作品中位数为 {result['baseline']}"
                observations.append(text)
        if not observations: observations.append('可用指标不足，只保留原始记录，不计算缺失指标')
        supported = [k for k, v in comparisons.items() if v['difference'] is not None]
        status = 'descriptive' if supported else 'insufficient'
        if not supported: flags.append('不足 3 篇可比且指标完整的历史作品，暂不判断相对表现')
        stronger = [RATE_FIELDS.get(k, '互动') for k in supported if comparisons[k]['difference'] > 0]
        hypothesis = ('本次'+ '、'.join(stronger)+'高于历史中位数；可能与选题、素材或表达有关，无法区分各因素贡献。'
                      if stronger else '现有数据不足以支持改写长期策略；继续收集同口径记录。')
        experiment = ('保留「'+post['pillar']+'」栏目与内容形式，下次只调整开头表达；观察同一窗口的收藏/阅读或播放比。'
                      if supported else '先补齐同账号、同形式、同流量类型的历史快照，再决定内容实验。')
        # Velocity only from distinct chronological snapshots of this same post, not correction order.
        older = [m for m in state['metrics'] if m['publication_id'] == post['id']
                 and parsed(m['observed_at']) < parsed(metric['observed_at']) and m['values'].get('likes') is not None]
        velocity = None
        if older and metric['values'].get('likes') is not None:
            prior = max(older, key=lambda m: (parsed(m['observed_at']), m['revision']))
            elapsed = (parsed(metric['observed_at'])-parsed(prior['observed_at'])).total_seconds()/3600
            delta = metric['values']['likes']-prior['values']['likes']
            if delta >= 0: velocity = dict(likes_per_hour=round(delta/elapsed, 3), metric_refs=[prior['id'], metric['id']])
            else: flags.append('点赞累计数下降：可能是修正或删除，暂不计算增长速度')
        refs = sorted({metric['id']} | {m['id'] for m in peers} | set(velocity['metric_refs'] if velocity else []))
        return dict(id=str(uuid4()), agent_id=self.agent_id, agent_version=self.version, schema_version=1,
            account_id=post['account_id'], publication_id=post['id'], metric_id=metric['id'],
            source_type=metric['source_type'], status=status, created_at=created_at,
            window=metric['window'], elapsed_hours=hours, window_quality=quality,
            observations=observations, hypotheses=[hypothesis], experiment=experiment,
            comparisons=comparisons, velocity=velocity, metric_refs=refs, excluded=excluded, flags=flags,
            limitations=['人工录入数据未由平台独立核实；只作描述性比较，不作因果归因。',
                        '窗口容差为目标时长的 0% 至 +25%；3 篇是展示门槛，不是统计充分性保证。',
                        '阅读/播放不是曝光；互动次数不是去重人数；暂不输出爆款概率。'],
            execution=dict(engine='deterministic_rules', model_calls=0, tools=['window_check','comparable_history','rate_calculation']))


def invalidate(state, publication_id, window):
    """Corrections invalidate all dependent analyses, including those using this post as baseline."""
    obsolete = {m['id'] for m in state['metrics'] if m['publication_id'] == publication_id and m['window'] == window}
    for report in state['analyses']:
        if obsolete.intersection(report['metric_refs']): report['status'] = 'superseded'
    for memory in state['memories']:
        if obsolete.intersection(memory.get('metric_refs', [memory['metric_id']])):
            memory['status'] = 'superseded'
    refresh_plans(state)


def refresh_plans(state):
    valid = {m['id'] for m in state['memories'] if m['status'] == 'accepted'}
    for plan in state['plans']:
        if plan['status'] not in ('revoked', 'needs_review') and not set(plan['memory_refs']) <= valid:
            plan['status'] = 'needs_review'

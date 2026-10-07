"""Account-conditioned retrieval / kernel regression, inspired by SKAPP.

This is NOT SKAPP's trained RRCP/vision-language graph network. Caller supplies
real, compatible encoder embeddings and same-account/same-metric observations.
We never convert a similarity into a viral probability. Time-ordered evaluation
and reference ablation are deliberately small, inspectable adaptations.
"""
from datetime import datetime, timezone
import math

METHOD = 'skapp_inspired_personalized_kernel_v1'


def _vector(value, dimension=None):
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 8192:
        raise ValueError('特征向量不能为空，且长度不能超过 8192')
    if dimension is not None and len(value) != dimension:
        raise ValueError('特征维度不一致，请使用同一个编码器重新处理')
    if any(isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x) for x in value):
        raise ValueError('特征向量必须是有限数字')
    scale = max(abs(x) for x in value)
    if not scale:
        raise ValueError('特征向量不能全为零')
    scaled = [x / scale for x in value]
    norm = math.sqrt(sum(x*x for x in scaled))
    return [x/norm for x in scaled]


def _cos(a, b):
    return max(0., min(1., sum(x*y for x, y in zip(a, b))))


def _date(value):
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            raise ValueError()
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise ValueError('历史时间必须包含时区') from None


def evaluate(profile_vector, candidates, history, config=None):
    """Return JSON-safe rankings; no database or model calls.

    All history must share metric/unit/observation horizon and ownership, which
    the service validates. Engineering gates (12 records / 5 backtests) are not
    statistical sufficiency guarantees. Backtesting uses current profile and
    config, so post-hoc profile tuning is not independent external validation.
    """
    profile = _vector(profile_vector)
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 5:
        raise ValueError('请提供 1 至 5 个候选选题')
    if not isinstance(history, list) or len(history) > 100:
        raise ValueError('最多使用 100 条历史作品')
    config = config or {}
    weights = [config.get(k, v) for k, v in [('text_weight', .55), ('image_weight', .25), ('profile_weight', .2)]]
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 or x > 1e6 for x in weights) or sum(weights) <= 0:
        raise ValueError('权重必须是非负有限数字，且至少一项大于零')
    total = sum(weights)
    weights = [x/total for x in weights]
    neighbors = config.get('neighbors', 5)
    if isinstance(neighbors, bool) or not isinstance(neighbors, int) or not 1 <= neighbors <= 20:
        raise ValueError('参考作品数量需为 1 至 20')
    def prepare(rows, historical):
        result, seen = [], set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'] or row['id'] in seen:
                raise ValueError('每条作品需要唯一的非空字符串 ID')
            seen.add(row['id'])
            item = dict(id=row['id'], title=str(row.get('title', ''))[:500], text=_vector(row.get('text_vector'), len(profile)), image=None)
            if row.get('image_vector') is not None:
                item['image'] = _vector(row['image_vector'], len(profile))
            if historical:
                value = row.get('value')
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1e12):
                    raise ValueError('历史指标必须是 0 至 1 万亿的有限数字')
                item.update(value=float(value) if value is not None else None, published=_date(row.get('published_at')), observed=_date(row['observed_at']) if row.get('observed_at') is not None else None)
                if value is not None and item['observed'] is None:
                    raise ValueError('有历史指标时必须提供采集时间')
                if item['observed'] is not None and item['observed'] < item['published']:
                    raise ValueError('数据采集时间不能早于发布时间')
            result.append(item)
        return result
    candidate_rows = prepare(candidates, False)
    all_history = prepare(history, True)
    now = datetime.now(timezone.utc)
    history_rows = sorted([r for r in all_history if r['published'] <= now and (r['observed'] is None or r['observed'] <= now)], key=lambda r: (r['published'], r['id']))

    eligible = [r for r in history_rows if r['value'] is not None]

    def profile_similarity(row):
        text = _cos(profile, row['text'])
        if row['image'] is None or weights[1] == 0:
            return text
        # ChineseCLIP text and image embeddings share the same feature space.
        denominator = weights[0] + weights[1]
        return (weights[0]*text + weights[1]*_cos(profile, row['image']))/denominator

    def similarity(query, ref):
        text = _cos(query['text'], ref['text'])
        image, mode = None, 'text_only'
        if weights[1] > 0:
            if query['image'] is not None and ref['image'] is not None:
                image, mode = _cos(query['image'], ref['image']), 'multimodal'
            elif query['image'] is not None:
                image, mode = _cos(query['image'], ref['text']), 'crossmodal'
            elif ref['image'] is not None:
                image, mode = _cos(query['text'], ref['image']), 'crossmodal'
        personal = profile_similarity(ref)
        denominator = weights[0] + weights[2] + (weights[1] if image is not None else 0)
        # If neither side has an image, an image-only setting uses text fallback.
        score = (weights[0]*text + weights[2]*personal + (weights[1]*image if image is not None else 0))/denominator if denominator else text
        return score, mode

    def select(query, pool, contributions):
        refs = []
        for ref in pool:
            if ref['id'] == query['id']:
                continue
            evidence = contributions.get(ref['id'], [])
            if evidence and sum(evidence)/len(evidence) < -1e-9:
                continue
            score, uses_image = similarity(query, ref)
            if score > 0:
                refs.append((score, ref, uses_image))
        return sorted(refs, key=lambda x: (-x[0], x[1]['id']))[:neighbors]

    def predict(refs):
        refs = [r for r in refs if r[1]['value'] is not None]
        denominator = sum(score*score for score, _, _ in refs)
        return sum(score*score*ref['value'] for score, ref, _ in refs)/denominator if denominator else None

    # Contribution observations cannot be used until their target's label exists.
    completed, backtests = [], []
    for target in eligible:
        pool = [r for r in eligible if r['published'] < target['published'] and r['observed'] <= target['published']]
        if len(pool) < 5:
            continue
        known = {}
        for observed, reference_id, gain in completed:
            if observed <= target['published']:
                known.setdefault(reference_id, []).append(gain)
        refs = select(target, pool, known)
        estimate = predict(refs)
        if estimate is None:
            continue
        baseline = sum(r['value'] for r in pool)/len(pool)
        error = abs(estimate-target['value'])
        backtests.append(dict(id=target['id'], reference_ids=[r['id'] for _, r, _ in refs], absolute_error=error, baseline_absolute_error=abs(baseline-target['value'])))
        if len(refs) >= 2:
            for index, (_, reference, _) in enumerate(refs):
                without = predict(refs[:index]+refs[index+1:])
                gain = abs(without-target['value'])-error
                completed.append((target['observed'], reference['id'], gain))
    contributions = {}
    for observed, reference_id, gain in completed:
        if observed <= now:
            contributions.setdefault(reference_id, []).append(gain)
    count = len(backtests)
    mae = sum(r['absolute_error'] for r in backtests)/count if count else None
    baseline_mae = sum(r['baseline_absolute_error'] for r in backtests)/count if count else None
    gate = len(eligible) >= 12 and count >= 5 and mae < baseline_mae - 1e-9
    reason = ('已通过当前账号的历史回测，可查看实验估计。' if gate else
              '历史不足 12 条，先按定位和图文匹配度筛选。' if len(eligible) < 12 else
              '有效历史回测不足 5 次，暂不显示热度估计。' if count < 5 else
              '历史回测尚未优于账号均值，暂不显示热度估计。')
    output = []
    for query in candidate_rows:
        refs = select(query, history_rows, contributions)
        personal = profile_similarity(query)
        relevance = sum(s for s, _, _ in refs)/len(refs) if refs else personal
        # Profile is always expressed in the ranking, including cold start.
        fit = weights[2]*personal + (1-weights[2])*relevance if refs else personal
        estimate = predict(refs) if gate and sum(r['value'] is not None for _, r, _ in refs) >= 3 else None
        details = []
        for score, ref, image_mode in refs:
            evidence = contributions.get(ref['id'], [])
            details.append(dict(id=ref['id'], title=ref['title'], similarity=round(score, 6), value=ref['value'], eligible=ref['value'] is not None, image_used=image_mode != 'text_only', image_mode=image_mode,
                contribution=sum(evidence)/len(evidence) if evidence else None, contribution_observations=len(evidence)))
        output.append(dict(id=query['id'], title=query['title'], fit_score=round(100*fit, 2), estimated_value=round(estimate, 4) if estimate is not None else None,
            reference_ids=[r['id'] for _, r, _ in refs], references=details,
            profile_similarity=round(personal, 6), image_mode=('multimodal' if any(x['image_mode'] == 'multimodal' for x in details) else 'crossmodal' if (query['image'] is not None and weights[1] > 0) or any(x['image_used'] for x in details) else 'text_only'),
            reason=(reason if estimate is not None or not gate else '此选题的可比参考数据不足，仅显示匹配度。') if refs else '尚无相似历史作品，仅展示与账号定位的匹配度。'))
    output.sort(key=lambda r: (r['estimated_value'] is None, -(r['estimated_value'] or 0), -r['fit_score'], r['id']))
    return dict(status='experimental_prediction' if gate else 'matching_only', method=METHOD,
        config=dict(zip(('text_weight', 'image_weight', 'profile_weight'), weights), neighbors=neighbors),
        validation=dict(history_count=len(history_rows), total_count=len(all_history), eligible_count=len(eligible), excluded_future_count=len(all_history)-len(history_rows), n_backtests=count, model_mae=mae, baseline_mae=baseline_mae, gate=gate, reason=reason,
            backtests=backtests, limitation='仅为当前定位和参数下的历史回测；工程门槛不代表统计充分，也不是独立前瞻验证或爆款概率。'), candidates=output)

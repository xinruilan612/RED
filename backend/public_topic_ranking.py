"""Read-only matching of collected public references; never predicts future heat.

Counts are snapshots, not comparable target labels. This module deliberately
keeps public evidence separate from the own-account prediction/training path.
"""
import math
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .topic_ranking import _vector, _cos, _date

METHOD = 'public_reference_multimodal_matching_v1'
BOUNDARY = ('公开互动数是采集时的累计记录，仅供查看参考内容；'
            '不代表你的未来阅读量、互动量或爆款概率。搜索结果不代表平台整体分布。')


def rank_public(profile_vector, candidates, samples, config=None):
    """Match up to 5 candidates against up to 100 public snapshot records.

    All embeddings must come from the same encoder. Missing counts remain None.
    Images are used only when their actual embedding exists; cross-modal text
    comparison is explicitly distinguished from inspecting both covers.
    """
    profile = _vector(profile_vector)
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 5:
        raise ValueError('请提供 1 至 5 个候选选题')
    if not isinstance(samples, list) or len(samples) > 100:
        raise ValueError('最多使用 100 条公开参考')
    config = config or {}
    weights = [config.get(k, default) for k, default in
               [('text_weight', .55), ('image_weight', .25), ('profile_weight', .2)]]
    if any(isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x)
           or not 0 <= x <= 1e6 for x in weights) or sum(weights) <= 0:
        raise ValueError('匹配权重必须为非负有限数字且不能全为零')
    weights = [x / sum(weights) for x in weights]
    neighbors = config.get('neighbors', 5)
    if isinstance(neighbors, bool) or not isinstance(neighbors, int) or not 1 <= neighbors <= 20:
        raise ValueError('参考作品数量需为 1 至 20')

    def prepare(rows, public):
        result, seen = [], set()
        for raw in rows:
            if not isinstance(raw, dict) or not isinstance(raw.get('id'), str) or not raw['id'] or raw['id'] in seen:
                raise ValueError('每条内容需要唯一的非空字符串 ID')
            seen.add(raw['id'])
            row = dict(raw)
            row['text_vector'] = _vector(raw.get('text_vector'), len(profile))
            row['image_vector'] = (_vector(raw['image_vector'], len(profile))
                                   if raw.get('image_vector') is not None else None)
            if public:
                url = str(raw.get('url', ''))
                parsed = urlsplit(url)
                if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError('公开参考需要可追溯的 HTTP 来源链接')
                row['collected_at'] = raw.get('observed_at') or raw.get('collected_at')
                row['_collected'] = _date(row['collected_at'])
                if raw.get('published_at'):
                    published = _date(raw['published_at'])
                    if published > row['_collected']:
                        raise ValueError('采集时间不能早于发布时间')
                counts = raw.get('counts', {})
                if not isinstance(counts, dict):
                    raise ValueError('公开互动记录格式不正确')
                for key in ('likes', 'saves', 'comments'):
                    value = counts.get(key, raw.get(key))
                    row[key] = value
                    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                              or not math.isfinite(value) or not 0 <= value <= 1e12):
                        raise ValueError('公开互动数必须是非负有限数字，缺失时请留空')
            result.append(row)
        return result

    queries = prepare(candidates, False)
    records = prepare(samples, True)
    now = datetime.now(timezone.utc)
    pool = [r for r in records if r['_collected'] <= now]

    def similarity(query, ref):
        text = _cos(query['text_vector'], ref['text_vector'])
        image, mode = None, 'text_only'
        if weights[1] > 0:
            if query['image_vector'] is not None and ref['image_vector'] is not None:
                image, mode = _cos(query['image_vector'], ref['image_vector']), 'multimodal'
            elif query['image_vector'] is not None:
                image, mode = _cos(query['image_vector'], ref['text_vector']), 'crossmodal'
            elif ref['image_vector'] is not None:
                image, mode = _cos(query['text_vector'], ref['image_vector']), 'crossmodal'
        personal = _cos(profile, ref['text_vector'])
        denominator = weights[0] + weights[2] + (weights[1] if image is not None else 0)
        score = ((weights[0] * text + weights[2] * personal + (weights[1] * image if image is not None else 0))
                 / denominator) if denominator else text
        return score, mode

    output = []
    for query in queries:
        ranked = [(similarity(query, ref), ref) for ref in pool]
        ranked = sorted((x for x in ranked if x[0][0] > 0), key=lambda x: (-x[0][0], x[1]['id']))[:neighbors]
        refs = []
        for (score, mode), ref in ranked:
            refs.append(dict(id=ref['id'], title=str(ref.get('title', ''))[:500], url=ref['url'],
                             source=str(ref.get('source', '公开参考'))[:100],
                             similarity=round(score, 6), likes=ref.get('likes'), saves=ref.get('saves'),
                             comments=ref.get('comments'), collected_at=ref['collected_at'],
                             published_at=ref.get('published_at'), image_mode=mode,
                             image_missing=ref['image_vector'] is None,
                             image_note=('参考封面未参与分析；按文本或跨模态匹配。' if ref['image_vector'] is None
                                         else '参考封面已参与匹配。' if mode != 'text_only' else '本次仅按文本匹配。'),
                             metric_semantics='cumulative_at_collection'))
        output.append(dict(id=query['id'], public_references=refs, public_sample_count=len(refs),
                           evidence_boundary=BOUNDARY))
    return dict(method=METHOD, status='public_reference_matching', public_sample_count=len(pool),
                excluded_future_count=len(records)-len(pool), candidates=output, evidence_boundary=BOUNDARY,
                prediction_available=False)

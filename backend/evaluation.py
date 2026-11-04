"""Deterministic, offline quality metrics for the multi-agent comparison study.

These functions score an already produced draft against a pre-registered gold
item. They never call a model and never touch the network, so the same numbers
can be recomputed from stored artefacts. Model-based judging is a separate,
optional layer: every metric here stays reproducible without it.

Nothing in this module decides that a draft is correct. It measures coverage,
citation support and forbidden-claim presence, and records the raw evidence so a
human can audit the score.
"""
import re

# Chinese/English content is tokenised with the same bigram scheme the retrieval
# path uses, so "covered" means what the product's own retrieval would consider
# related rather than a second, silently different definition.
from backend.knowledge import tokens

SENTENCE_SPLIT = re.compile(r'[。！？!?\n]+')
# A sentence is treated as checkable when it asserts something a source could
# confirm or contradict: a quantity, a unit, a price, or a model-like token.
CHECKABLE = re.compile(r'\d')
MODEL_TOKEN = re.compile(r'[A-Za-z][A-Za-z0-9_-]*\d[A-Za-z0-9_-]*|\d+\s*(?:mL|ml|L|g|kg|mm|cm|m|W|V|Ah|元|块|寸|英寸)')
DEFAULT_COVERAGE_THRESHOLD = 0.5


def sentences(text):
    return [part.strip() for part in SENTENCE_SPLIT.split(str(text)) if part.strip()]


def checkable_sentences(text):
    return [s for s in sentences(text) if CHECKABLE.search(s) or MODEL_TOKEN.search(s)]


def overlap_ratio(left, right):
    """Share of left's distinct tokens also present in right (0.0 to 1.0)."""
    left_tokens = set(tokens(left))
    if not left_tokens:
        return 0.0
    right_tokens = set(tokens(right))
    return len(left_tokens & right_tokens) / len(left_tokens)


def fact_support_rate(draft, references, threshold=DEFAULT_COVERAGE_THRESHOLD):
    """Share of checkable sentences backed by at least one frozen reference.

    Support means the sentence's distinctive tokens are substantially present in
    a reference span, or a model/unit token appears verbatim. It proves lexical
    grounding only; it does not prove the reference is authoritative.
    """
    rows = []
    refs = [str(r) for r in (references or []) if str(r).strip()]
    for sentence in checkable_sentences(draft):
        best, matched = 0.0, None
        literal = [token for token in MODEL_TOKEN.findall(sentence) if token.lower() in ' '.join(refs).lower()]
        for index, ref in enumerate(refs):
            score = overlap_ratio(sentence, ref)
            if score > best:
                best, matched = score, index
        supported = best >= threshold or bool(literal)
        rows.append({'sentence': sentence, 'best_overlap': round(best, 6),
                     'reference_index': matched if supported else None,
                     'literal_token': literal[0] if literal else None,
                     'supported': supported})
    total = len(rows)
    supported = sum(1 for row in rows if row['supported'])
    return {'total': total, 'supported': supported,
            'rate': round(supported / total, 6) if total else None, 'evidence': rows}


DISCLAIMER = re.compile(
    # Only absence-of-data phrasing counts as a disclaimer. A bare negative such as
    # "没有夸大宣传" must NOT excuse a neighbouring forbidden assertion, so a plain
    # 没有/无 only qualifies when it governs 数据/依据/信息/结论 within the clause.
    r'(?:未(?:提供|给出|列出|列|包含|说明|引申|标注|宣称|涉及|提及|声称|写明|公布|披露|验证|测试)|'
    r'缺少|缺失|不含|暂不|不作|不提供|'
    r'(?:没有|无|并无|未有)[^。！？!?\n]{0,24}?(?:数据|依据|信息|结论|说明|支持|来源))'
)


def sentence_at(text, index):
    """Sentence containing ``index``; used to read the local claim context."""
    start = 0
    for mark in '。！？!?\n':
        found = text.rfind(mark, 0, index)
        if found + 1 > start:
            start = found + 1
    ends = [pos for pos in (text.find(mark, index) for mark in '。！？!?\n') if pos != -1]
    end = min(ends) + 1 if ends else len(text)
    return text[start:end]


def forbidden_claim_hits(draft, patterns):
    """Return the forbidden assertions that the draft actually makes.

    A mention inside a disclaimer ("没有持妆时长、保湿效果等未提供数据") is the
    opposite of a violation: the draft is correctly saying the material lacks it.
    Only non-disclaimed occurrences count. Negation is detected per sentence with
    a fixed marker set; it is a heuristic, not full negation parsing, and the raw
    matches are kept so a human can audit every decision.
    """
    text = str(draft)
    hits, disclaimed = [], []
    for pattern in patterns or []:
        try:
            found = re.search(pattern, text)
        except re.error as error:
            raise ValueError('invalid forbidden pattern %r: %s' % (pattern, error)) from None
        if not found:
            continue
        sentence = sentence_at(text, found.start())
        row = {'pattern': pattern, 'match': found.group(0), 'sentence': sentence}
        if DISCLAIMER.search(sentence):
            disclaimed.append(row)
        else:
            hits.append(row)
    return {'hits': hits, 'disclaimed': disclaimed, 'any_hit': bool(hits),
            'patterns': len(patterns or [])}


def expected_point_coverage(draft, points, threshold=DEFAULT_COVERAGE_THRESHOLD):
    """Share of pre-registered must-cover points that the draft covers."""
    text = str(draft)
    rows = []
    for point in points or []:
        best, best_sentence = 0.0, None
        for sentence in sentences(text):
            score = overlap_ratio(point, sentence)
            if score > best:
                best, best_sentence = score, sentence
        rows.append({'point': point, 'best_overlap': round(best, 6),
                     'sentence': best_sentence, 'covered': best >= threshold})
    total = len(rows)
    covered = sum(1 for row in rows if row['covered'])
    return {'total': total, 'covered': covered,
            'rate': round(covered / total, 6) if total else None, 'evidence': rows}


def draft_text(content):
    """Flatten a stored draft the same way the product defines its publishable text."""
    if not isinstance(content, dict):
        return ''
    parts = [content.get('selected_title') or '', content.get('body') or '', content.get('cta') or '']
    parts.extend(content.get('tags') or [])
    return '\n'.join(str(part) for part in parts)


def score_draft(content, references, item):
    """Score one draft against one gold item. No model, no network, no state."""
    text = draft_text(content)
    body = str(content.get('body') or '') if isinstance(content, dict) else ''
    return {
        'chars': len(body),
        'fact_support': fact_support_rate(text, references),
        'forbidden': forbidden_claim_hits(text, item.get('forbidden_claims')),
        'coverage': expected_point_coverage(text, item.get('expected_points')),
    }


def aggregate(records, arm_key='arm'):
    """Per-arm means over records produced by score_draft, skipping null metrics."""
    arms = {}
    for record in records or []:
        arm = record.get(arm_key)
        bucket = arms.setdefault(arm, {'n': 0, '_fact': [], '_coverage': [], '_forbidden': [], '_chars': []})
        bucket['n'] += 1
        score = record.get('score') or {}
        for name, key in (('fact', 'fact_support'), ('coverage', 'coverage')):
            rate = (score.get(key) or {}).get('rate')
            if rate is not None:
                bucket['_' + name].append(rate)
        hit_any = (score.get('forbidden') or {}).get('any_hit')
        if hit_any is not None:
            bucket['_forbidden'].append(1.0 if hit_any else 0.0)
        if isinstance(score.get('chars'), int):
            bucket['_chars'].append(score['chars'])
    def mean(values):
        return round(sum(values) / len(values), 6) if values else None
    return {arm: {'n': bucket['n'], 'fact_support_rate': mean(bucket['_fact']),
                  'expected_point_coverage': mean(bucket['_coverage']),
                  'forbidden_hit_rate': mean(bucket['_forbidden']),
                  'mean_body_chars': mean(bucket['_chars'])}
            for arm, bucket in sorted(arms.items(), key=lambda kv: str(kv[0]))}

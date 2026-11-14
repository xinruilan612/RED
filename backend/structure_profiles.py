"""Deterministic writing-role extraction and evidence-conditioned adaptation.

This is a versioned rule baseline, not model training or semantic understanding.
Profiles contain generic functions and provenance, never reusable source prose.
Field availability means supplied material exists, not independent verification.
"""
import copy
import hashlib
import json
import re

VERSION = 'structure-rules-v1'
FUNCTIONS = {
    'HOOK': '引出当前任务的阅读动机',
    'PROBLEM': '说明当前任务要解决的问题',
    'CONTEXT': '交代当前任务的背景与适用范围',
    'EVIDENCE': '用当前任务的证据支撑判断',
    'SOLUTION': '组织有依据的方案或操作步骤',
    'WARNING': '说明限制和需要核对的条件',
    'CTA': '给出与正文一致的下一步建议',
}
ALIASES = {
    'specs': 'product_specs', 'parameters': 'product_specs', '产品参数': 'product_specs',
    'comparison': 'comparison_specs', '对比参数': 'comparison_specs',
    'experience': 'firsthand_record', 'firsthand': 'firsthand_record', '亲测记录': 'firsthand_record',
    'audience': 'user_need', '需求': 'user_need', 'steps': 'use_steps', '步骤': 'use_steps',
}


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _classification(value):
    nested = value.get('classification') or value.get('creation_classification') or value.get('creation') or {}
    metadata = value.get('metadata') or {}
    nested = nested if isinstance(nested, dict) else {}
    nested = nested or metadata.get('classification') or {}
    nested = nested if isinstance(nested, dict) else {}
    result = {key: nested.get(key, value.get(key)) for key in ('domains', 'channel', 'format')}
    domains = result['domains']
    result['domains'] = sorted(set(d for d in domains if isinstance(d, str))) if isinstance(domains, list) else []
    for key in ('channel', 'format'):
        result[key] = result[key] if isinstance(result[key], str) else ''
    return result


def _segments(text):
    # Blank lines/line breaks or sentence boundaries; positions address ORIGINAL
    # text, including CRLF, rather than an untraceable normalized copy.
    for match in re.finditer(r'[^\r\n。！？!?；;]+[。！？!?；;]?', text):
        raw = match.group()
        left = len(raw) - len(raw.lstrip())
        right = len(raw.rstrip())
        if right > left:
            yield match.start() + left, match.start() + right, raw[left:right]


def _role(text, index, count):
    if re.search(r'亲测|实测|我(?:用了|使用|体验)|使用了|用了.*(?:天|周|月)|体验.*(?:天|周|月)', text):
        return 'EVIDENCE', ['firsthand_record']
    if re.search(r'对比|相比|比较|优于|不如|更便宜|更快', text):
        return 'EVIDENCE', ['comparison_specs']
    if re.search(r'注意|慎用|不适合|局限|限制|禁忌|避坑|切勿|不能', text):
        return 'WARNING', ['limitations']
    if re.search(r'收藏|评论|关注|试试|行动|下一步|欢迎|记得', text):
        return 'CTA', []
    if re.search(r'参数|规格|容量|重量|价格|续航|\d\s*(?:毫升|克|公斤|元|小时|[mMkKgGlLwW])', text):
        return 'EVIDENCE', ['product_specs']
    if re.search(r'步骤|首先|然后|最后|方法|解决|建议|操作|清洗|安装', text):
        return 'SOLUTION', ['use_steps']
    if re.search(r'困扰|问题|痛点|怎么办|难以|为什么|如何|纠结', text):
        return ('HOOK' if index == 0 else 'PROBLEM'), ['user_need']
    if index == 0:
        return 'HOOK', []
    if index == count - 1 and count > 2:
        return 'CTA', []
    return 'CONTEXT', []


def extract_profile(source):
    """Extract generic writing slots from one authorized example source dict.

    Callers enforce source ownership before calling. Only source identity,
    version, page and absolute offsets survive into the provenance.
    """
    text = source.get('text') or source.get('body') or ''
    text = text if isinstance(text, str) else ''
    matches = list(_segments(text))[:32]
    slots = []
    offset = source.get('offset', 0)
    offset = offset if type(offset) is int and offset >= 0 else 0
    for index, (start, end, segment) in enumerate(matches):
        role, needs = _role(segment, index, len(matches))
        # A single sentence can mix experience, comparison and specifications.
        # Evidence dependencies are a union, independent of the primary role.
        needs = set(needs)
        if re.search(r'亲测|实测|我(?:用了|使用|体验)|使用了|用了.*(?:天|周|月)|体验.*(?:天|周|月)', segment):
            needs.add('firsthand_record')
        if re.search(r'对比|相比|比较|优于|不如|更便宜|更快', segment):
            needs.add('comparison_specs')
        if re.search(r'参数|规格|容量|重量|价格|续航|\d\s*(?:毫升|克|公斤|元|小时|[mMkKgGlLwW])', segment):
            needs.add('product_specs')
        needs = sorted(needs)
        slots.append({'slot_id': 's%d' % (index + 1), 'role': role,
                      'function': FUNCTIONS[role], 'needs': needs,
                      'position': {'start': offset + start, 'end': offset + end,
                                   'unit': 'unicode_codepoint'},
                      'segment_sha256': _digest(segment)})
    provenance = {key: source[key] for key in ('source_id', 'document_id', 'version', 'page')
                  if key in source and isinstance(source[key], (str, int))}
    provenance['text_sha256'] = _digest(text)
    identity = json.dumps({'provenance': provenance, 'classification': _classification(source),
                           'version': VERSION}, ensure_ascii=False, sort_keys=True)
    return {'schema_version': 1, 'extraction_method': VERSION,
            'profile_id': 'structure:' + _digest(identity)[:24],
            'classification': _classification(source), 'provenance': provenance,
            'slots': slots, 'limitations': ['规则标签可能误判；资料存在不代表已核实事实。',
                                           '仅复用段落功能，不能继承原作者经历、参数和结论。']}


def _fallback():
    return [{'slot_id': 'base%d' % index, 'role': role, 'function': FUNCTIONS[role], 'needs': []}
            for index, role in enumerate(('HOOK', 'CONTEXT', 'WARNING', 'CTA'), 1)]


def select_profile(profiles, task, available_fields):
    """Select same-domain/channel/form profile, then adapt unsupported slots.

    ``strict_isolation=False`` permits cross-domain structures but still requires
    exact channel/form; default is strict. No source plaintext enters the result.
    Inputs are not mutated. Selection and tie breaks are deterministic.
    """
    classification = _classification(task)
    available = {ALIASES.get(field, field) for field in available_fields if isinstance(field, str)}
    candidates, rejected = [], []
    for profile in profiles:
        candidate = profile.get('classification') or {}
        reasons = []
        overlap = set(candidate.get('domains') or []) & set(classification['domains'])
        if task.get('strict_isolation', True) and not overlap:
            reasons.append('DOMAIN_MISMATCH')
        for key in ('channel', 'format'):
            if not classification.get(key) or candidate.get(key) != classification[key]:
                reasons.append(key.upper() + '_MISMATCH')
        if not profile.get('slots'):
            reasons.append('EMPTY_PROFILE')
        if reasons:
            rejected.append({'profile_id': profile.get('profile_id'), 'reasons': reasons})
            continue
        missing = sum(len(set(slot.get('needs') or []) - available) for slot in profile['slots'])
        candidates.append((missing, -len(overlap), str(profile.get('profile_id', '')), profile))
    candidates.sort(key=lambda item: item[:3])
    selected = candidates[0][3] if candidates else None
    slots = copy.deepcopy(selected['slots']) if selected else _fallback()
    adaptations = []
    for slot in slots:
        missing = sorted(set(slot.get('needs') or []) - available)
        if not missing:
            slot['adaptation'] = 'retain'
            continue
        original_role = slot['role']
        slot.update(role='WARNING', function='列出需要核对的事项；不陈述未经支持的体验、对比或参数结论',
                    needs=[], adaptation='replace_with_checklist')
        adaptations.append({'slot_id': slot['slot_id'], 'original_role': original_role,
                            'missing_fields': missing, 'action': 'replace_with_checklist',
                            'reason': '当前资料不具备该段所需证据，改为待核对事项并缩小表达范围。'})
    return {'schema_version': 1, 'method': VERSION,
            'selected_profile_id': selected['profile_id'] if selected else None,
            'fallback': selected is None, 'slots': slots, 'adaptations': adaptations,
            'rejected_profiles': sorted(rejected, key=lambda item: str(item['profile_id'])),
            'selection_rule': '先隔离领域渠道形式，再最小化缺失证据字段数，最后按稳定ID排序',
            'verification_boundary': '资料字段存在仅用于结构适配，不等于事实核验或原创保证。'}


def copy_risk(text, sources):
    """Limited exact contiguous-match hints for THIS reference set only.

    Checks at most 20 references and 20,000 codepoints per text. Whitespace-only
    and short/common fragments are excluded. Positions address supplied texts;
    a match can be a legitimate quotation or a common expression. This function
    must never be used as an automatic approval/rejection condition.
    """
    text = text if isinstance(text, str) else ''
    sources = list(sources or [])
    limit = 20000
    matches = []
    truncated = len(text) > limit or len(sources) > 20
    for index, source in enumerate(sources[:20]):
        source_text = source.get('text') or source.get('body') or ''
        source_text = source_text if isinstance(source_text, str) else ''
        truncated = truncated or len(source_text) > limit
        # Index one occurrence per 12-character seed. This is a bounded risk
        # detector, not exhaustive plagiarism alignment; repeated boilerplate
        # cannot trigger a quadratic sequence comparison.
        reference = source_text[:limit]
        draft = text[:limit]
        seeds = {}
        for start in range(max(0, len(reference) - 11)):
            seeds.setdefault(reference[start:start + 12], start)
        cursor = 0
        while cursor + 12 <= len(draft):
            start = seeds.get(draft[cursor:cursor + 12])
            if start is None:
                cursor += 1
                continue
            size = 12
            while cursor + size < len(draft) and start + size < len(reference) and draft[cursor + size] == reference[start + size]:
                size += 1
            fragment = draft[cursor:cursor + size]
            meaningful = len(re.findall(r'[\w\u4e00-\u9fff]', fragment))
            if meaningful >= 10:
                matches.append({'source_id': source.get('source_id'), 'source_index': index,
                                'draft_start': cursor, 'draft_end': cursor + size,
                                'source_start': start, 'source_end': start + size,
                                'length': size, 'match_sha256': _digest(fragment)})
            cursor += size
    matches.sort(key=lambda item: (-item['length'], item['source_index'], item['draft_start']))
    return {'method': 'limited-contiguous-match-v1', 'risk_detected': bool(matches),
            'matches': matches[:20], 'checked_sources': min(len(sources), 20),
            'truncated': truncated or len(matches) > 20, 'automatic_approval_condition': False,
            'scope': '仅比较本次参考中至少12字符且至少10个文字字符的连续匹配；不是全网查重或原创保证，须人工判断。'}

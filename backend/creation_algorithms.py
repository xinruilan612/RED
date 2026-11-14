"""Snapshot-scoped decision layer for the existing four-role writer.

Model candidates are untrusted semantic suggestions. Program checks provenance,
budgets and IDs; a valid quotation is not a proof of semantic entailment.
No provider calls, permissions or final approval authority live in this module.
"""
import copy
import re

from backend.contracts import require
from backend.workflow import digest

VERSION = 'evidence-creation-v3'


def options(value=None):
    value = {} if value is None else value
    require(isinstance(value, dict) and set(value) <= {'enabled', 'ask_questions', 'coverage', 'structure'}
            and all(type(v) is bool for v in value.values()), 'INVALID_INPUT', '创作算法设置无效')
    enabled = value.get('enabled', True)
    result = {'enabled': enabled, 'ask_questions': enabled and value.get('ask_questions', False)}
    # Preserve the old serialized defaults; explicit per-module switches enable
    # reproducible ablation without changing historical snapshots.
    for key in ('coverage', 'structure'):
        if key in value:
            result[key] = enabled and value[key]
    return result


def enabled(context):
    # Historical tasks have no implicit new behavior.
    return context.get('algorithm_options', {}).get('enabled') is True


def feature(context, name):
    return enabled(context) and context['algorithm_options'].get(name, True) is True


def candidates(context, stage, value):
    """Bound optional model extensions without changing legacy role contracts."""
    if not enabled(context):
        return {}
    field = {'audience': 'reader_questions', 'research': 'missing_facts',
             'strategy': 'content_modules'}.get(stage)
    if not field or field not in value:
        return {}
    rows = value[field]
    require(isinstance(rows, list) and len(rows) <= 12, 'MODEL_OUTPUT_INVALID', '算法候选最多12项')
    allowed = {
        'reader_questions': {'id', 'question', 'priority'},
        'missing_facts': {'id', 'field', 'question', 'blocks', 'priority'},
        'content_modules': {'id', 'title', 'covers', 'source_id', 'quote', 'length'},
    }[field]
    cleaned = []
    for row in rows:
        require(isinstance(row, dict), 'MODEL_OUTPUT_INVALID', '算法候选格式无效')
        item = {k: copy.deepcopy(v) for k, v in row.items() if k in allowed}
        for k, v in item.items():
            if k in ('covers', 'blocks'):
                require(isinstance(v, list) and len(v) <= 12 and all(isinstance(x, str) and len(x) <= 100 for x in v),
                        'MODEL_OUTPUT_INVALID', '算法候选关联无效')
            elif k == 'length':
                require(type(v) is int and 1 <= v <= 10000, 'MODEL_OUTPUT_INVALID', '模块预计字数无效')
            else:
                require(isinstance(v, str) and len(v) <= (1000 if k == 'quote' else 300),
                        'MODEL_OUTPUT_INVALID', '算法候选文字无效')
        cleaned.append(item)
    return {field: cleaned}


def _terms(text):
    from backend.knowledge import tokens
    return set(tokens(text))


def coverage_evidence_matches(question, quote):
    """Conservative aspect gate for proposed coverage, not an entailment solver.

Reject obvious property swaps and unsupported comparison/experience slots.
Ambiguous language remains uncounted. A positive result is still tentative.
"""
    if len(_terms(question) & _terms(quote)) < 2:
        return False
    # Observed pilot failure: a list of USB ports was counted as answering
    # whether those ports can charge or output video. Location is not capability.
    # Unknown material remains a gap, not positive evidence for the requested use.
    if re.search(r'未提供|未实测|未测试|未知|尚不清楚|缺少.{0,10}(?:资料|依据|记录)', quote):
        return False
    aspects = [('高度|净高|多高', '高度|净高|高'), ('宽度|多宽', '宽度|宽'),
               ('容量|水箱|净含量', '容量|水箱|净含量'), ('价格|多少钱|预算', '价格|元|售价'),
               ('散热|散热口', '散热'), ('重量|多重', '重量|克|公斤|kg'),
               ('面积|多大房间', '面积|平方米|平米'),
               ('几次|频率|加水', '频率|加水|次|每天|每日'),
               ('步骤|怎么安装|安装方法', '步骤|首先|然后|安装方法')]
    aspects += [('视频输出|显示输出', '视频输出|显示输出|显示器输出'),
                ('充电|供电', '充电|供电'), ('麦克风|话筒', '麦克风|话筒'),
                ('直连|直接连接', '直连|直接连接'),
                ('同时|一并', '同时|一并'), ('驱动', '驱动'),
                ('握感|握持|舒适', '握感|握持|舒适'),
                ('延迟|响应速度', '延迟|响应速度'), ('噪音|噪声|静音', '噪音|噪声|静音')]
    for query_pattern, evidence_pattern in aspects:
        if re.search(query_pattern, question) and not re.search(evidence_pattern, quote):
            return False
    if re.search(r'位置|在哪|朝向', question) and not re.search(r'位于|位置[为在：:]|朝向|左侧|右侧|背面|前方|后方|底部|顶部', quote):
        return False
    if re.search(r'后果|影响|原因|为什么|留给|多出|用于什么', question) and not re.search(r'导致|因为|因此|影响|否则|会造成|用于|预留', quote):
        return False
    if re.search(r'一样|区别|差异|对比|相比|不同版本', question):
        if not re.search(r'相比|对比|分别|区别|相同|不同|一样', quote):
            return False
        if re.search(r'未提供|没有|未知|暂无|未查到', quote):
            return False
    if re.search(r'能装|能否安装|装不下|装得下', question):
        if not re.search(r'至少|不低于|不少于|净高|安装条件|安装要求|不得', quote):
            return False
    return True


def build(run):
    """Derive reproducible decisions solely from this run's frozen inputs."""
    from backend.live import creation_groups, factual_records
    from backend.planning import plan
    from backend.gap_ranker import rank_questions
    from backend.structure_profiles import extract_profile, select_profile
    audience = run.branches.get('audience', {}).get('data', {})
    research = run.branches.get('research', {}).get('data', {})
    strategy = next((a['value'] for a in reversed(run.artifacts)
                     if a['stage'] == 'strategy' and a.get('snapshot_id') == run.snapshot_id), {})
    raw = audience.get('reader_questions') or [
        {'question': q, 'priority': 'high' if i < 2 else 'medium'}
        for i, q in enumerate(audience.get('pain_points', []) + audience.get('content_opportunities', []))]
    requirements = []
    for i, item in enumerate(raw[:10]):
        question = item.get('question', '').strip()
        if question:
            # Server IDs and a finite importance rubric, never model probabilities.
            requirements.append({'id': 'r%d' % (i + 1), 'question': question,
                                 'weight': {'high': 3, 'medium': 2, 'low': 1}.get(item.get('priority'), 2),
                                 'origin': 'model_suggested_reader_need'})
    if not requirements:
        requirements = [{'id': 'r1', 'question': run.context['topic'], 'weight': 3,
                         'origin': 'user_topic_fallback'}]
    lookup = {s['source_id']: s for s in factual_records(run.context)}
    modules, rejected = [], []
    raw_modules = strategy.get('content_modules', [])
    for i, item in enumerate(raw_modules):
        source = lookup.get(item.get('source_id'))
        quote = item.get('quote', '').strip()
        covers = [r['id'] for r in requirements if r['id'] in item.get('covers', [])
                  and coverage_evidence_matches(r['question'], quote)]
        if not source or not quote or quote not in source['text'] or not covers:
            rejected.append({'id': 'candidate%d' % (i+1), 'reason': 'unmatched_fact_quote_or_requirement'})
            continue
        modules.append({'id': 'm%d' % (i+1), 'title': item.get('title') or quote[:40],
                        'covers': covers, 'length': max(20, item.get('length', 80)),
                        'source_ids': [source['source_id']], 'quote': quote,
                        'supported': True, 'support_scope': 'quotation_location_only', 'statement_type': 'assertion'})
    if not modules:
        # Legacy outputs remain runnable. Matching here is explicitly lexical,
        # and unaligned facts are not falsely counted as covered requirements.
        for i, fact in enumerate(research.get('facts', [])[:12]):
            source = lookup.get(fact.get('source_id'))
            quote = str(fact.get('quote', '')).strip()
            if not source or not quote or quote not in source['text']:
                continue
            covers = [r['id'] for r in requirements if coverage_evidence_matches(r['question'], quote)]
            modules.append({'id': 'f%d' % (i+1), 'title': quote[:50], 'covers': covers,
                            'length': max(30, min(150, len(quote) + 20)),
                            'source_ids': [source['source_id']], 'quote': quote, 'supported': True,
                            'support_scope': 'lexical_candidate_not_entailment', 'statement_type': 'assertion'})
    classification = run.context.get('creation_classification', {})
    budget = classification.get('word_count', run.context.get('word_count', 300))
    budget = budget if type(budget) is int and 20 <= budget <= 10000 else 300
    planning = plan(requirements, modules, budget)
    planning.update(requirements=requirements, rejected_candidates=rejected,
                    scope='预计篇幅与候选覆盖；不是正文覆盖或独立事实核验')
    gap_rows = research.get('missing_facts') or [
        {'question': q, 'field': 'unspecified', 'priority': 'high' if research.get('core_gap') else 'low'}
        for q in research.get('gaps', [])]
    gaps = []
    for i, item in enumerate(gap_rows[:10]):
        question = item.get('question', '').strip()
        if not question:
            continue
        field = item.get('field', '')
        key = field + question
        critical = any(w in key for w in ('型号', '版本', '安装', '尺寸', '预算', '需求', 'product_version', 'model'))
        known_ids = {r['id'] for r in requirements}
        blocks = [b for b in item.get('blocks', []) if b in known_ids]
        if not blocks:
            blocks = [r['id'] for r in requirements
                      if r['id'] not in planning['covered_requirement_ids']
                      and len(_terms(r['question']) & _terms(question)) >= 2]
        if not blocks:
            blocks = ['gap:'+field if field else 'gap:%d' % (i+1)]
        gaps.append({'id': 'g%d' % (i+1), 'question': question, 'field': field,
                     'importance': 1.0 if critical else 0.6 if research.get('core_gap') else 0.2,
                     'blocks': blocks,
                     'resolvable': 1 if field in ('model', 'product_version', 'user_need', 'budget', 'experience') or critical else 0.5,
                     'cost': 1, 'origin': 'rule_ranked_model_gap'})
    ranking = rank_questions(gaps, max_questions=2, threshold=0.5)
    if run.supplements or run.context.get('algorithm_questions_status') in ('skipped', 'answered'):
        ranking['already_handled'] = True
    groups = creation_groups(run.context)
    profiles = [extract_profile(s) for s in groups['examples'][:3]]
    # Availability means present in verified-location records, not truth verified.
    fact_text = '\n'.join(f['quote'] for f in research.get('facts', [])
                          if f.get('source_id') in lookup and f.get('quote') in lookup[f['source_id']]['text'])
    available = ['user_need']
    positive = [s for s in re.split(r'[。！？!?\n；;]', fact_text)
                if not re.search(r'未提供|没有|缺少|不含|未测试|未实测|未知|未查到|暂无|无依据', s)]
    specification = re.compile(r'(容量|净含量|高度|宽度|长度|尺寸|重量|价格|续航|功率).{0,18}\d|\d\s*(?:毫升|厘米|毫米|公斤|元|小时|[mMkKgGlLwW])')
    if any(specification.search(s) for s in positive):
        available.append('product_specs')
    if any(specification.search(s) and re.search(r'对比|相比|分别', s)
           and len(set(re.findall(r'[A-Za-z][A-Za-z0-9]*\d[A-Za-z0-9]*', s))) >= 2
           for s in positive):
        available.append('comparison_specs')
    # Mere mentions and negations are not a personal experience record. Require
    # an explicit user-marked record plus a first-person action and reject
    # absence/negation anywhere in that record's sentence.
    user_records = re.split(r'[。！？!?\n；;]', run.context.get('material', ''))
    if any(re.search(r'(亲测记录|实测记录|个人体验)[:：].*我(?:使用|用了|体验|测试)', s)
           and not re.search(r'没有|未|无|不曾|缺少|不要|不能', s) for s in user_records):
        available.append('firsthand_record')
    if any(re.search(r'步骤|首先|然后|安装方法|操作方法', s) for s in positive):
        available.append('use_steps')
    if re.search(r'注意|限制|不适合|不得|不能|至少|前提', fact_text):
        available.append('limitations')
    structure = select_profile(profiles, classification, available)
    structure['profiles'] = profiles
    structure['available_fields'] = available
    structure['availability_scope'] = '字段存在启发式；不证明事实真实或充分'
    return {'schema_version': 1, 'algorithm_version': VERSION, 'snapshot_id': run.snapshot_id,
            'input_hash': digest({'branches': run.branches, 'strategy': strategy,
                                  'sources': list(lookup.values()), 'classification': classification,
                                  'options': run.context.get('algorithm_options')}),
            'active_modules': {name: feature(run.context, name) for name in ('coverage', 'structure')},
            'planning': planning, 'gap_ranking': ranking, 'structure': structure}


def refresh(run):
    if enabled(run.context) and set(run.branches) >= {'audience', 'research'}:
        run.context['algorithm_state'] = build(run)
        inspect_draft(run)


def should_ask(run):
    state = run.context.get('algorithm_state', {})
    return (enabled(run.context) and run.context['algorithm_options'].get('ask_questions') is True
            and not run.supplements and not run.context.get('algorithm_questions_status')
            and bool(state.get('gap_ranking', {}).get('questions')))


def model_plan(run):
    """Bounded plan projection; keep full computation traces out of paid prompts."""
    state = run.context.get('algorithm_state', {})
    if not enabled(run.context) or state.get('snapshot_id') != run.snapshot_id:
        return None
    result = {'scope': '只借鉴段落功能；内容来自当前事实；无依据时收窄。规划覆盖不等于成稿覆盖。',
              'active_modules': {name: feature(run.context, name) for name in ('coverage', 'structure')}}
    if feature(run.context, 'coverage'):
        result.update(requirements=state['planning']['requirements'],
                      selected_modules=state['planning']['selected_modules'],
                      uncovered_requirement_ids=state['planning']['uncovered_requirement_ids'],
                      budget=state['planning']['budget'])
    if feature(run.context, 'structure'):
        result['structure'] = {k: state['structure'].get(k) for k in ('selected_profile_id', 'slots', 'adaptations', 'fallback')}
    return result


def inspect_draft(run):
    """Diagnostic only: never changes an approval decision or pretends semantic scoring."""
    from backend.structure_profiles import copy_risk
    from backend.live import creation_groups
    state = run.context.get('algorithm_state')
    if not state or state.get('snapshot_id') != run.snapshot_id or not run.drafts:
        return
    content = run.drafts[-1]
    if content.get('snapshot_id') != run.snapshot_id:
        state.pop('review', None)
        return
    if not feature(run.context, 'structure'):
        state.pop('review', None)
        return
    text = content['content'].get('body', '')
    state['review'] = {'draft_ref': content['ref'], 'content_hash': content['content_hash'],
                       'copy_risk': copy_risk(text, creation_groups(run.context)['examples']),
                       'scope': '仅对本次参考做连续文本风险检测；不证明全网原创或事实正确'}

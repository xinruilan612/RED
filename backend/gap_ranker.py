"""Explainable optional question ranking; heuristic scores are not information entropy."""
import math
from copy import deepcopy
import re
import unicodedata


def rank_questions(gaps, max_questions=2, threshold=0.5):
    """Choose high-value questions, discounting already covered dependent blocks.

    Importance and resolvability are finite rule weights in [0,1]; no inferred
    probability is claimed. Unknown resolvability defaults to zero. Missing blocks
    use the gap ID so independent questions remain distinguishable.
    """
    def scalar(value, name, upper=None):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (upper is not None and value > upper):
            raise ValueError(name + ' is outside its finite allowed range')
        return float(value)
    if not isinstance(gaps, list):
        raise ValueError('gaps must be a list')
    if isinstance(max_questions, bool) or not isinstance(max_questions, int) or not 0 <= max_questions <= 10:
        raise ValueError('max_questions must be an integer from 0 to 10')
    threshold = scalar(threshold, 'threshold')
    pending, skipped, ids = [], [], set()
    for gap in gaps:
        if not isinstance(gap, dict) or not isinstance(gap.get('id'), str) or not gap['id'].strip() or gap['id'] in ids:
            raise ValueError('gap IDs must be unique nonempty strings')
        ids.add(gap['id'])
        question = gap.get('question', '')
        if not isinstance(question, str):
            raise ValueError('question must be text')
        importance = scalar(gap.get('importance', 0), 'importance', 1)
        resolvable = gap.get('resolvable', 0)
        if isinstance(resolvable, bool):
            resolvable = int(resolvable)
        resolvable = scalar(resolvable, 'resolvable', 1)
        cost = scalar(gap.get('cost', 1), 'cost')
        blocks = gap.get('blocks', [])
        if not isinstance(blocks, list) or not all(isinstance(b, str) and b.strip() for b in blocks):
            raise ValueError('blocks must be nonempty string IDs')
        key = re.sub(r'[\W_]+', '', unicodedata.normalize('NFKC', question).casefold())
        if gap.get('resolved') is True or gap.get('skipped') is True or not key or not resolvable:
            reason = 'resolved' if gap.get('resolved') is True else 'user_skipped' if gap.get('skipped') is True else 'empty_question' if not key else 'not_resolvable'
            skipped.append({'id': gap['id'], 'reason': reason})
            continue
        pending.append({'gap': deepcopy(gap), 'id': gap['id'], 'key': key, 'importance': importance,
                        'resolvable': resolvable, 'cost': cost, 'blocks': set(blocks) or {'gap:' + gap['id']}})
    questions, steps, covered, asked = [], [], set(), set()
    while pending and len(questions) < max_questions:
        candidates = []
        for item in pending:
            new = item['blocks'] - covered
            value = item['importance'] * (1 + len(new)) * item['resolvable'] / (1 + item['cost']) if new and item['key'] not in asked else 0.0
            candidates.append({'id': item['id'], 'value': value, 'new_blocks': sorted(new),
                               'importance': item['importance'], 'resolvable': item['resolvable'], 'cost': item['cost']})
        best = min(candidates, key=lambda c: (-c['value'], c['id']))
        if best['value'] <= 0 or best['value'] < threshold:
            break
        item = next(p for p in pending if p['id'] == best['id'])
        question = deepcopy(item['gap'])
        question.update(value=best['value'], new_blocks=best['new_blocks'], can_skip=True,
                        skip_effect='保留资料缺口，收窄写作范围，不自动补成事实')
        questions.append(question)
        covered.update(item['blocks'])
        asked.add(item['key'])
        steps.append({'step': len(steps) + 1, 'selected_id': item['id'],
                      'candidates': sorted(candidates, key=lambda c: c['id'])})
        pending.remove(item)
    for item in pending:
        reason = 'duplicate_question' if item['key'] in asked else 'redundant_blocks' if not item['blocks'] - covered else 'question_limit' if len(questions) >= max_questions else 'below_threshold'
        skipped.append({'id': item['id'], 'reason': reason})
    return {'algorithm': 'rule-weighted-gap-value-v1', 'is_information_entropy': False,
            'rule': 'importance * (1 + new_block_count) * resolvable / (1 + cost)',
            'questions': questions, 'skipped': skipped, 'threshold': threshold,
            'max_questions': max_questions, 'steps': steps, 'can_continue_without_answers': True}

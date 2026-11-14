#!/usr/bin/env python3
"""Offline, synthetic mechanism benchmark. No network, model calls or user study."""
import argparse
import itertools
import json
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.planning import plan
from backend.gap_ranker import rank_questions
from backend.structure_profiles import extract_profile, select_profile

SEED = 20261102
DISCLAIMER = ('全部为固定种子生成的构造任务，仅评估算法机制；不是实际生成质量、独立事实核验、'
              '真人阅读评分、用户效果、产品优越性或获奖证据。无模型调用、无网络和费用。')


def _objective(chosen, weights, penalty=0.15):
    counts = {key: sum(key in set(item['covers']) for item in chosen) for key in weights}
    covered = sum(weights[key] for key, count in counts.items() if count)
    repeated = sum(weights[key] * max(0, count - 1) for key, count in counts.items())
    return covered, covered - penalty * repeated


def _eligible(modules):
    return [m for m in modules if m.get('supported') is True and m.get('source_ids')]


def _first_fit(modules, budget):
    selected, used = [], 0
    for item in _eligible(modules):
        if used + item['length'] <= budget:
            selected.append(item)
            used += item['length']
    return selected


def _optimal(modules, weights, budget):
    eligible = _eligible(modules)
    best, best_score = [], 0.0
    for size in range(len(eligible) + 1):
        for group in itertools.combinations(eligible, size):
            if sum(item['length'] for item in group) > budget:
                continue
            score = _objective(group, weights)[1]
            if score > best_score:
                best, best_score = list(group), score
    return best


def _summary_plan(chosen, weights, budget):
    covered, objective = _objective(chosen, weights)
    return {'selected_ids': [m['id'] for m in chosen], 'coverage_numerator': covered,
            'coverage_denominator': sum(weights.values()), 'objective': objective,
            'used_budget': sum(m['length'] for m in chosen), 'budget': budget}


def build_report(task_count=24, seed=SEED):
    if isinstance(task_count, bool) or not isinstance(task_count, int) or not 24 <= task_count <= 200:
        raise ValueError('task_count must be an integer from 24 to 200')
    rng = random.Random(seed)
    tasks = []
    domains = ['beauty', 'photography', 'digital', 'furniture']
    for index in range(task_count):
        reqs = [dict(id='r%d' % j, question='构造需求%d' % j, weight=rng.randint(1, 5)) for j in range(5)]
        weights = {r['id']: r['weight'] for r in reqs}
        budget = rng.choice([45, 60, 75])
        modules = [dict(id='m%d' % j, covers=rng.sample(list(weights), rng.randint(1, 3)),
                        length=rng.choice([15, 20, 25, 30]), supported=True,
                        source_ids=['synthetic-fact-%d' % index]) for j in range(7)]
        modules.insert(0, dict(id='unsupported', covers=list(weights), length=1, supported=False, source_ids=[]))
        # Explicit greedy trap: included to expose the absence of an optimum guarantee.
        if index == 0:
            reqs = [dict(id='a', weight=3), dict(id='b', weight=2), dict(id='c', weight=2)]
            weights = {r['id']: r['weight'] for r in reqs}
            budget = 5
            modules = [dict(id='ratio-trap', covers=['a'], length=3, supported=True, source_ids=['fact']),
                       dict(id='better-total', covers=['b', 'c'], length=5, supported=True, source_ids=['fact'])]
        greedy = plan(reqs, modules, budget, solver='greedy')
        exact = plan(reqs, modules, budget)
        no_weights = plan([dict(r, weight=1) for r in reqs], modules, budget)
        # Experimental input transformation only: production evidence gate stays on.
        ungated_input = [dict(m, supported=True, source_ids=m['source_ids'] or ['ABLATION-UNVERIFIED']) for m in modules]
        no_gate = plan(reqs, ungated_input, budget)
        admissible_coverage = set(r for m in _eligible(modules) for r in m['covers'])
        original_ids = {m['id'] for m in _eligible(modules)}
        coverage = {'requirements': reqs, 'modules': modules, 'budget': budget,
                    'first_fit': _summary_plan(_first_fit(modules, budget), weights, budget),
                    'greedy': _summary_plan(greedy['selected_modules'], weights, budget),
                    'enumerated_optimal': _summary_plan(_optimal(modules, weights, budget), weights, budget),
                    'exact': _summary_plan(exact['selected_modules'], weights, budget),
                    'without_weights': _summary_plan(no_weights['selected_modules'], weights, budget),
                    'without_evidence_gate': _summary_plan(no_gate['selected_modules'], weights, budget),
                    'candidate_recall': {'numerator': len(admissible_coverage), 'denominator': len(reqs)},
                    'objective_gap_vs_greedy': exact['objective_gap_vs_greedy'],
                    'exact_objective_gap_vs_reference': _objective(_optimal(modules, weights, budget), weights)[1] - exact['objective_value'],
                    'solve_ms': {'exact': exact['elapsed_ms'], 'greedy': greedy['elapsed_ms']},
                    'unsupported_selected': {'exact': sum(m['id'] not in original_ids for m in exact['selected_modules']),
                                             'without_evidence_gate': sum(m['id'] not in original_ids for m in no_gate['selected_modules'])},
                    'optimality_scope': exact['optimality_scope'],
                    'decision_log': greedy['steps'], 'excluded': greedy['excluded']}
        gaps = [dict(id='color', question='颜色是什么？', importance=0.1, cost=0, resolvable=True, blocks=['color']),
                dict(id='version', question='具体版本是什么？', importance=1, cost=0.5, resolvable=True,
                     blocks=['dimensions', 'installation', 'accessories']),
                dict(id='experience', question='有本人的实测记录吗？', importance=0.7, cost=1, resolvable=True,
                     blocks=['experience', 'limitations']),
                dict(id='price', question='当前价格是多少？', importance=0.2, cost=2, resolvable=True, blocks=['price'])]
        if index % 3:
            rng.shuffle(gaps)
        answers = {'color': ['color'], 'version': ['dimensions', 'installation', 'accessories'],
                   'experience': ['experience', 'limitations'], 'price': ['price']}
        ranked = rank_questions(gaps, max_questions=2)
        ranked_ids = [q['id'] for q in ranked['questions']]
        ordered_ids = [q['id'] for q in gaps[:2]]
        def resolved(ids):
            return sorted(set(block for key in ids for block in answers[key]))
        gap_report = {'input': gaps, 'standard_answer_blocks': answers, 'question_limit': 2,
                      'in_order': {'asked_ids': ordered_ids, 'resolved_blocks': resolved(ordered_ids)},
                      'ranked': {'asked_ids': ranked_ids, 'resolved_blocks': resolved(ranked_ids)},
                      'total_resolvable_blocks': len(resolved(list(answers))), 'decision_log': ranked['steps']}
        classification = dict(domains=[domains[index % len(domains)]], channel='xiaohongshu', format='note')
        sentinel = '原作者独特句子标记XYZ%d' % index
        text = '为什么选购会纠结？\n我用了30天，' + sentinel + '。\n产品容量为999L。\n对比另一款，价格更便宜。\n首先核对安装步骤。\n注意适用限制。\n欢迎收藏。'
        profile = extract_profile(dict(source_id='synthetic-source-%d' % index, version=1,
                                       text=text, classification=classification))
        all_fields = ['user_need', 'firsthand_record', 'product_specs', 'comparison_specs', 'use_steps', 'limitations']
        available = rng.sample(all_fields, index % (len(all_fields) + 1))
        selected = select_profile([profile], dict(classification=classification), available)
        def unsupported(slots):
            return sum(bool(set(slot.get('needs', [])) - set(available)) for slot in slots)
        metadata = json.dumps({'profile': profile, 'selected': selected}, ensure_ascii=False)
        structure = {'classification': classification, 'available_fields': available,
                     'slot_count': len(profile['slots']), 'raw_unsupported_slots': unsupported(profile['slots']),
                     'adapted_unsupported_slots': unsupported(selected['slots']),
                     'adaptations': selected['adaptations'], 'selected_profile_id': selected['selected_profile_id'],
                     'source_prose_marker_leaked_in_metadata': sentinel in metadata,
                     'source_fact_string_leaked_in_metadata': '999L' in metadata,
                     'boundary': '仅检查结构元数据的证据需求和原文标记；不代表生成稿事实正确或全网原创。'}
        tasks.append({'id': 'synthetic-%02d' % index, 'coverage': coverage, 'gaps': gap_report, 'structure': structure})
    coverage_totals = {}
    for group in ['first_fit', 'greedy', 'enumerated_optimal', 'exact', 'without_weights', 'without_evidence_gate']:
        parts = [t['coverage'][group] for t in tasks]
        numerator = sum(p['coverage_numerator'] for p in parts)
        denominator = sum(p['coverage_denominator'] for p in parts)
        coverage_totals[group] = {'numerator': numerator, 'denominator': denominator,
                                  'weighted_coverage': numerator / denominator,
                                  'used_budget': sum(p['used_budget'] for p in parts),
                                  'budget': sum(p['budget'] for p in parts),
                                  'objective_sum': sum(p['objective'] for p in parts)}
    gap_totals = {}
    for group in ['in_order', 'ranked']:
        gap_totals[group] = {'resolved_block_numerator': sum(len(t['gaps'][group]['resolved_blocks']) for t in tasks),
                            'resolvable_block_denominator': sum(t['gaps']['total_resolvable_blocks'] for t in tasks),
                            'questions_asked': sum(len(t['gaps'][group]['asked_ids']) for t in tasks),
                            'question_budget': 2 * task_count}
    failure_cases = []
    for task in tasks:
        cov = task['coverage']
        if cov['greedy']['objective'] + 1e-9 < cov['enumerated_optimal']['objective']:
            failure_cases.append({'task_id': task['id'], 'kind': 'greedy_below_enumerated_optimum',
                                  'greedy_objective': cov['greedy']['objective'],
                                  'optimal_objective': cov['enumerated_optimal']['objective']})
        if cov['greedy']['coverage_numerator'] < cov['first_fit']['coverage_numerator']:
            failure_cases.append({'task_id': task['id'], 'kind': 'greedy_coverage_below_first_fit'})
    return {'schema_version': 2, 'seed': seed, 'task_count': task_count, 'data_type': 'constructed_synthetic',
            'disclaimer': DISCLAIMER, 'model_calls': 0, 'network_requests': 0,
            'summary': {'coverage': coverage_totals, 'gaps': gap_totals,
                        'coverage_diagnostics': {
                            'candidate_recall_numerator': sum(t['coverage']['candidate_recall']['numerator'] for t in tasks),
                            'candidate_recall_denominator': sum(t['coverage']['candidate_recall']['denominator'] for t in tasks),
                            'exact_objective_gap_vs_reference_sum': sum(t['coverage']['exact_objective_gap_vs_reference'] for t in tasks),
                            'exact_objective_gain_vs_greedy_sum': sum(t['coverage']['objective_gap_vs_greedy'] for t in tasks),
                            'unsupported_selected_exact': sum(t['coverage']['unsupported_selected']['exact'] for t in tasks),
                            'unsupported_selected_without_gate': sum(t['coverage']['unsupported_selected']['without_evidence_gate'] for t in tasks),
                            'mean_exact_solve_ms': sum(t['coverage']['solve_ms']['exact'] for t in tasks) / task_count,
                            'mean_greedy_solve_ms': sum(t['coverage']['solve_ms']['greedy'] for t in tasks) / task_count,
                            'timing_boundary': 'wall-clock measurements vary; candidate-pool objective optimum does not imply global retrieval optimum'},
                        'structure': {'slots_denominator': sum(t['structure']['slot_count'] for t in tasks),
                                      'raw_unsupported_numerator': sum(t['structure']['raw_unsupported_slots'] for t in tasks),
                                      'adapted_unsupported_numerator': sum(t['structure']['adapted_unsupported_slots'] for t in tasks),
                                      'metadata_prose_leaks_numerator': sum(t['structure']['source_prose_marker_leaked_in_metadata'] for t in tasks),
                                      'metadata_fact_leaks_numerator': sum(t['structure']['source_fact_string_leaked_in_metadata'] for t in tasks),
                                      'metadata_tasks_denominator': task_count}},
            'failure_cases': failure_cases, 'tasks': tasks}


def write_report(report, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'benchmark.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    lines = ['# 三算法离线受控机制基准', '', report['disclaimer'], '',
             '固定种子：%s；构造任务：%s；模型调用：0；网络请求：0。' % (report['seed'], report['task_count']), '',
             '## 需求覆盖：相同字数预算与证据准入', '',
             '输入顺序 first-fit、贪心与正式精确解均先排除无依据模块。独立枚举作为小案例参考；正式求解器在不超过12个合法候选时也执行精确枚举。目标为加权覆盖减去 0.15 倍重复权重。', '',
             '| 方法 | 覆盖权重分子/分母 | 使用字数预算/可用预算 | 目标值总和 |',
             '| --- | --- | --- | --- |']
    for name, value in report['summary']['coverage'].items():
        lines.append('| %s | %s/%s | %s/%s | %.3f |' % (name, value['numerator'], value['denominator'], value['used_budget'], value['budget'], value['objective_sum']))
    diagnostics = report['summary']['coverage_diagnostics']
    lines += ['', '候选需求召回（构造标注分子/分母）：%s/%s。' % (diagnostics['candidate_recall_numerator'], diagnostics['candidate_recall_denominator']),
              '', '精确解相对贪心目标增益总和：%.3f；相对独立枚举目标差距总和：%.3f。' % (diagnostics['exact_objective_gain_vs_greedy_sum'], diagnostics['exact_objective_gap_vs_reference_sum']),
              '', '平均规划耗时：精确 %.3f ms，贪心 %.3f ms；耗时随机器与运行波动，不参与确定性结果承诺。' % (diagnostics['mean_exact_solve_ms'], diagnostics['mean_greedy_solve_ms']),
              '', '无证据模块选择数：正式精确解 %s，去证据门控消融 %s。' % (diagnostics['unsupported_selected_exact'], diagnostics['unsupported_selected_without_gate']),
              '', '无权重消融以等权选择、再按原始权重计分；无证据门控仅在离线复制输入，不能作为生产写作配置。',
              '', '精确保证仅限当前合法候选池、给定覆盖关系与预计字数目标；不保证模型候选池完整、全局检索最优、生成稿长度或质量。']
    lines += ['', '## 关键缺口提问：固定标准答案模拟', '',
              '标准答案提前绑定能解决的 block；这不是实际用户回答，block 数量不等于真人价值。两组每任务最多提问两次。', '',
              '| 方法 | 解决block分子/可解决block分母 | 提问数/提问预算 |', '| --- | --- | --- |']
    for name, value in report['summary']['gaps'].items():
        lines.append('| %s | %s/%s | %s/%s |' % (name, value['resolved_block_numerator'], value['resolvable_block_denominator'], value['questions_asked'], value['question_budget']))
    s = report['summary']['structure']
    lines += ['', '## 结构迁移：槽位适配与元数据隔离', '',
              '未适配槽位：%s/%s；适配后仍缺证据槽位：%s/%s。' % (s['raw_unsupported_numerator'], s['slots_denominator'], s['adapted_unsupported_numerator'], s['slots_denominator']),
              '', '结构元数据出现原文独特标记：%s/%s；出现原文参数字符串：%s/%s。' % (s['metadata_prose_leaks_numerator'], s['metadata_tasks_denominator'], s['metadata_fact_leaks_numerator'], s['metadata_tasks_denominator']),
              '', '字段存在只表示已提供资料。这里没有生成正文，不能据此推断内容真实、结构自然或不抄袭。', '', '## 失败案例', '']
    lines += ['- `%s`：%s。' % (failure['task_id'], failure['kind']) for failure in report['failure_cases']] or ['本批未观察到记录规则覆盖的失败；不代表一般保证。']
    lines += ['', '全部输入、逐任务分子分母、标准答案映射和决策日志保存在 benchmark.json，可复算。', '']
    (output / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    return output / 'benchmark.json', output / 'REPORT.md'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='输出目录，生成 benchmark.json 和 REPORT.md')
    parser.add_argument('--tasks', type=int, default=24)
    parser.add_argument('--seed', type=int, default=SEED)
    args = parser.parse_args()
    paths = write_report(build_report(args.tasks, args.seed), args.output)
    print(json.dumps({'json': str(paths[0]), 'markdown': str(paths[1]), 'data_type': 'constructed_synthetic'}, ensure_ascii=False))


if __name__ == '__main__':
    main()

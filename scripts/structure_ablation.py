#!/usr/bin/env python3
"""Offline structural isolation/slot mechanism study, never a quality study."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from backend.creation_algorithms import build
from backend.structure_profiles import extract_profile, select_profile
from backend.workflow import Run

DISCLAIMER = ('刻意把一篇异领域干扰放在候选首位的受控压力用例；只验证领域隔离和缺证据槽位替换机制，'
              '不能外推真实检索污染比例、文章质量、人工Macro-F1或真实创作者效果。没有模型或网络调用。')


def sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def available_evidence(task):
    """Reuse production availability heuristics on only the frozen initial facts.

    This is an offline adapter, not a model-generated research result. It neither
    reads fixed answers nor treats proposed human gold as a verified judgment.
    """
    material = task['material']
    if any(material[f['start']:f['end']] != f['quote'] for f in task['facts']):
        raise ValueError('Fact span changed: '+task['id'])
    context = {'topic': task['topic'], 'material': material,
               'creation_classification': task['input']['creation'],
               'creation_retrieval': {'groups': {'methods': [], 'examples': [], 'facts': []}},
               'algorithm_options': {'enabled': True, 'coverage': False, 'structure': True,
                                     'ask_questions': False}}
    facts = [{'source_id': 'user-material', 'quote': f['quote']} for f in task['facts']]
    run = Run('controlled-study-owner', 'controlled:'+task['id'], context=context,
              branches={'audience': {'data': {'reader_questions': [], 'pain_points': [], 'content_opportunities': []}},
                        'research': {'data': {'facts': facts, 'gaps': [], 'core_gap': False}}})
    fields = build(run)['structure']['available_fields']
    return {'fields': fields, 'method': 'production creation_algorithms.build availability heuristics',
            'material_sha256': sha(material),
            'fact_spans': copy.deepcopy(task['facts']),
            'boundary': '字段存在启发式，不证明槽位的每项具体事实充分或现实真实性；统一答案未进入输入'}


def admissible(profile, classification):
    candidate = profile['classification']
    return (bool(set(candidate['domains']) & set(classification['domains']))
            and candidate['channel'] == classification['channel']
            and candidate['format'] == classification['format'])


def summarize_slots(slots, available):
    missing = [{'slot_id': slot['slot_id'], 'missing_fields': sorted(set(slot.get('needs', []))-set(available))}
               for slot in slots]
    missing = [item for item in missing if item['missing_fields']]
    return {'slot_count': len(slots), 'unsupported_slot_count': len(missing),
            'unsupported_dependency_count': sum(len(item['missing_fields']) for item in missing),
            'unsupported_slots': missing}


def evaluate_task(task, source_pool):
    classification = task['input']['creation']
    own = task['reference_example']
    canonical = next((s for s in source_pool if s['source_id'] == own['source_id']), None)
    if canonical is None or canonical['text'] != own['text'] or any(
            canonical['classification'].get(k) != own['classification'].get(k)
            for k in ('domains', 'channel', 'format')):
        raise ValueError('Task reference does not match frozen source pool: '+task['id'])
    # Deliberate ordering bias, frozen before any outcome: first foreign source
    # in lexical source-ID order outranks the supplied same-domain reference.
    foreign = sorted((s for s in source_pool if not set(s['classification']['domains']) & set(classification['domains'])),
                     key=lambda source: source['source_id'])
    if not foreign:
        raise ValueError('Controlled stress pool needs a foreign-domain distractor')
    candidates = [foreign[0], own]
    seen = {s['source_id'] for s in candidates}
    candidates.extend(s for s in sorted(source_pool, key=lambda source: source['source_id'])
                      if s['source_id'] not in seen)
    profiles = [extract_profile(source) for source in candidates]
    evidence = available_evidence(task)
    available = evidence['fields']
    trace = [{'rank': index+1, 'source_id': source['source_id'],
              'classification': profile['classification'], 'profile_id': profile['profile_id'],
              'text_sha256': sha(source['text']), 'admissible': admissible(profile, classification),
              'source_ref': source.get('provenance', {})}
             for index, (source, profile) in enumerate(zip(candidates, profiles))]
    base = {'task_id': task['id'], 'category': task['category'], 'classification': classification,
            'availability': evidence, 'candidate_sources': trace,
            'candidate_bias': '首位人为放入异领域干扰，其次为任务参考；余下按source_id排序；不模拟真实检索分布',
            'human_quality_score': None, 'human_macro_f1': None}
    results = []
    results.append({**copy.deepcopy(base), 'arm': 'A', 'label': '无结构迁移',
                    'selected_source_id': None, 'selected_profile_id': None,
                    'slots': [], 'slot_count': 0, 'unsupported_slot_count': None,
                    'unsupported_dependency_count': None, 'unsupported_slots': [],
                    'foreign_source_selected': None, 'adaptations': [],
                    'metric_status': 'not_applicable_no_structure_transfer',
                    'steps': [{'operation': 'structure_disabled', 'source_id': None}]})
    eligible = [i for i, p in enumerate(profiles) if admissible(p, classification)]
    for arm in ('B', 'C', 'D'):
        selected = 0 if arm == 'B' else eligible[0] if eligible else None
        if selected is None:
            # The supplied task reference is expected to match, but keep failure
            # explicit instead of silently borrowing a foreign article.
            result = select_profile([], classification, available)
            profile, source = None, None
        else:
            profile, source = profiles[selected], candidates[selected]
            result = (select_profile([profile], classification, available) if arm == 'D'
                      else {'slots': copy.deepcopy(profile['slots']), 'adaptations': [],
                            'selected_profile_id': profile['profile_id'], 'fallback': False})
        slots = result['slots']
        results.append({**copy.deepcopy(base), 'arm': arm,
                        'label': {'B':'仅提取、不隔离、不适配','C':'提取并隔离、不适配','D':'提取、隔离并适配'}[arm],
                        'selected_source_id': source['source_id'] if source else None,
                        'selected_profile_id': result['selected_profile_id'], 'slots': slots,
                        **summarize_slots(slots, available),
                        'foreign_source_selected': not admissible(profile, classification) if profile else False,
                        'adaptations': result['adaptations'], 'fallback': result['fallback'],
                        'metric_status': 'mechanism_only',
                        'steps': [{'operation': 'extract_rules', 'source_ids': [s['source_id'] for s in candidates]},
                                  {'operation': 'preserve_input_order' if arm=='B' else 'exact_domain_channel_form_filter',
                                   'rejected_source_ids': [] if arm=='B' else [s['source_id'] for s,p in zip(candidates,profiles) if not admissible(p,classification)]},
                                  {'operation':'choose_first_eligible','source_id':source['source_id'] if source else None},
                                  {'operation':'adapt_missing_evidence' if arm=='D' else 'adaptation_disabled',
                                   'source_id':source['source_id'] if source else None}]})
    return results


def study(dataset):
    tasks = json.loads((dataset/'20tasks.json').read_text())['items']
    corpus = json.loads((dataset/'30structure_samples.json').read_text())['items']
    pool = []
    for sample in corpus:
        text = (dataset/sample['text_path']).read_text()
        if sha(text) != sample['text_sha256']:
            raise ValueError('Structure source fingerprint changed: '+sample['id'])
        pool.append({'source_id': 'sprint-example:'+sample['id'], 'text': text,
                     'classification': {'domains':[sample['domain']], 'channel':sample['channel'], 'format':sample['format']},
                     'provenance': {'path':sample['text_path'],'text_sha256':sample['text_sha256'],
                                    'source_kind':sample['source_kind']}})
    cases = [row for task in tasks for row in evaluate_task(task,pool)]
    summary = []
    for arm in 'ABCD':
        selected = [row for row in cases if row['arm']==arm]
        summary.append({'arm':arm,'tasks':len(selected),
                        'transferred_slot_count':sum(row['slot_count'] for row in selected),
                        'foreign_source_selected_tasks':None if arm=='A' else sum(row['foreign_source_selected'] for row in selected),
                        'unsupported_slot_count':None if arm=='A' else sum(row['unsupported_slot_count'] for row in selected),
                        'unsupported_dependency_count':None if arm=='A' else sum(row['unsupported_dependency_count'] for row in selected),
                        'metric_status':'not_applicable_no_structure_transfer' if arm=='A' else 'mechanism_only'})
    return {'schema':'youji-structure-ablation/1','disclaimer':DISCLAIMER,
            'task_count':len(tasks),'structure_source_count':len(corpus),
            'dataset_sha256':sha((dataset/'20tasks.json').read_text()),
            'corpus_sha256':sha((dataset/'30structure_samples.json').read_text()),
            'module_sha256':{name:hashlib.sha256((APP/'backend'/name).read_bytes()).hexdigest()
                             for name in ('structure_profiles.py','creation_algorithms.py')},
            'paid_calls':0,'human_labels_completed':False,'summary':summary,'cases':cases}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,default=APP/'docs/evidence/sprint-20261102/dataset')
    parser.add_argument('--output',type=Path,default=APP.parent/'output/冲刺提升验收-20261102/结构消融')
    args=parser.parse_args()
    report=study(args.dataset)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    lines=['# 结构四组机制消融（离线受控）','',DISCLAIMER,'',
           '20任务、30篇自编结构文章；A无结构为N/A，不能把其零移入槽位解释为优于其他组；B故意首选异领域干扰。',
           '可用字段由同一生产启发式从同一初始事实得到；固定补料答案不进入输入。没有正文生成、真人标注或质量评分。','',
           '|组|任务|移入槽位|选入异领域任务|缺证据槽位|缺证据依赖|', '|---|---:|---:|---:|---:|---:|']
    for row in report['summary']:
        display=lambda x:'N/A' if x is None else str(x)
        lines.append('|'+ '|'.join(display(row[k]) for k in ('arm','tasks','transferred_slot_count','foreign_source_selected_tasks','unsupported_slot_count','unsupported_dependency_count'))+'|')
    lines.extend(['','D的缺证据槽位变少由替换规则直接造成，只能证明规则被执行，不能据此证明文章正确、连贯或更好。',
                  'B与C比较隔离效果，C与D比较槽位适配；A无结构不参与缺料比例比较。',
                  '完整候选来源、哈希、可用字段、位置与每步决策见results.json。原始人工标注表仍为空。'])
    (args.output/'说明与汇总.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(report['summary'],ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()

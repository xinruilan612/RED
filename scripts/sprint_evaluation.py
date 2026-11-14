#!/usr/bin/env python3
"""Offline blinded human evaluation; never generates articles or invents scores."""
import argparse
import csv
import html
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path

GROUPS = ('A', 'B', 'C', 'D', 'E')
METRICS = ('completeness', 'factuality', 'coherence', 'naturalness', 'usefulness')
LABELS = ('HOOK', 'PROBLEM', 'CONTEXT', 'EVIDENCE', 'SOLUTION', 'WARNING', 'CTA')


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def write_csv(path, fields, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def registered_groups(groups):
    if not isinstance(groups,(list,tuple)) or len(groups)<2 or len(set(groups))!=len(groups) or not set(groups)<=set(GROUPS):
        raise ValueError('预注册 groups 必须为至少两种不重复的 A/B/C/D/E 组')
    return tuple(groups)


def blind_package(data, output, reviewers=3, seed=20261102, groups=GROUPS):
    groups=registered_groups(groups)
    tasks = data.get('tasks', [])
    if not tasks or not isinstance(tasks, list):
        raise ValueError('输入必须包含非空 tasks 数组；没有文章不能创建盲评包')
    if not 2 <= reviewers <= 20:
        raise ValueError('reviewers 必须为2至20')
    rng = random.Random(seed)
    seen = set()
    records = []
    for task in tasks:
        task_id = task.get('task_id')
        if not isinstance(task_id, str) or not task_id.strip() or task_id in seen:
            raise ValueError('task_id 必须为非空且唯一的字符串')
        seen.add(task_id)
        articles = task.get('articles', [])
        if len(articles) != len(groups) or {a.get('group') for a in articles} != set(groups):
            raise ValueError('每个任务必须恰好包含全部预注册组：'+','.join(groups)+'；不允许静默漏组')
        for article in articles:
            if not isinstance(article.get('text'), str) or not article['text'].strip():
                raise ValueError('文章正文不能为空')
            records.append({'task_id': task_id, 'group': article['group'],
                            'brief': str(task.get('brief', '')), 'text': article['text']})
    output = Path(output)
    # Never silently replace a previous experiment or its evaluator files.
    if (output/'researcher-private'/'mapping.json').exists() or (output/'reviewers').exists():
        raise ValueError('目标已存在盲评包，请选择新目录，避免覆盖正在评分的实验')
    shuffled = list(range(len(records)))
    rng.shuffle(shuffled)
    mapping, presentations = {}, []
    for number, index in enumerate(shuffled, 1):
        identity = 'P%04d' % number
        record = records[index]
        mapping[identity] = {'task_id': record['task_id'], 'group': record['group']}
        presentations.append({'article_id': identity, 'brief': record['brief'], 'text': record['text']})
    names = ['reviewer-%02d' % (i+1) for i in range(reviewers)]
    write_json(output/'researcher-private'/'mapping.json', {'schema_version': 1, 'seed': seed,
        'groups': list(groups), 'reviewer_ids': names, 'articles': mapping,
        'controls': {**data.get('controls', {}),'registered_groups':list(groups),'evaluation_purpose':data.get('purpose','practice')}, 'scope': '组名与随机种子仅供研究者，禁止随评委包分发。练习包只用于熟悉评审流程，不作真实文章质量或算法有效性证明。'})
    for reviewer in names:
        order = presentations.copy()
        rng.shuffle(order)
        folder = output/'reviewers'/reviewer
        rows = [{'reviewer_id': reviewer, 'article_id': row['article_id'], **{m:'' for m in METRICS}, 'notes':''} for row in order]
        write_csv(folder/'scores.csv', ('reviewer_id','article_id',*METRICS,'notes'), rows)
        pages = ['<!doctype html><meta charset="utf-8"><title>文章盲评</title><style>body{max-width:860px;margin:40px auto;font:18px/1.7 sans-serif}article{border-top:1px solid #ccc;padding:24px 0}pre{white-space:pre-wrap}</style>',
                 '<h1>文章评价</h1><p>请逐篇在 scores.csv 填写五项 1–5 分：内容完整性、事实准确性、逻辑连贯性、表达自然度、实际使用价值。留空表示未评价，不能以0替代。事实判断请依据相同任务的核对资料，未核对时留空。请勿猜测实验分组。</p>']
        for row in order:
            pages.append('<article><h2>%s</h2><p>任务：%s</p><pre>%s</pre></article>' % tuple(html.escape(row[k]) for k in ('article_id','brief','text')))
        (folder/'articles.html').write_text('\n'.join(pages),encoding='utf-8')
    return {'status':'awaiting_human_scores','tasks':len(tasks),'articles':len(records),'reviewers':reviewers,
            'groups':list(groups),'scope':'练习用于熟悉评审流程；未完成真实任务、独立评分及实验控制时不能作质量证明。',
            'distribution':'仅分别分发 reviewers 中对应评委目录；禁止分发 researcher-private。原文和简报中的显式组名需人工排查。'}


def clustered_ci(differences, repetitions=5000, seed=20261102):
    """Each element is ONE task's paired evaluator-averaged difference."""
    if len(differences) < 2:
        return None
    rng = random.Random(seed)
    samples = sorted(statistics.mean(rng.choices(differences, k=len(differences))) for _ in range(repetitions))
    return [samples[int((len(samples)-1)*.025)], samples[int((len(samples)-1)*.975)]]


def aggregate_scores(mapping_data, rows, repetitions=5000, seed=20261102):
    if repetitions < 100:
        raise ValueError('bootstrap 重采样次数至少100')
    mapping = mapping_data['articles']
    groups=registered_groups(mapping_data.get('groups',GROUPS))
    task_groups=defaultdict(list)
    for item in mapping.values():task_groups[item['task_id']].append(item['group'])
    if any(len(actual)!=len(groups) or set(actual)!=set(groups) for actual in task_groups.values()):
        raise ValueError('映射中的任务组集合与预注册groups不一致')
    reviewers = mapping_data['reviewer_ids']
    values = defaultdict(dict)
    missing, seen = [], set()
    for number, row in enumerate(rows, 2):
        reviewer, article = row.get('reviewer_id'), row.get('article_id')
        if reviewer not in reviewers or article not in mapping:
            raise ValueError('未知评委/文章 ID，第 %d 行' % number)
        key = (reviewer, article)
        if key in seen:
            raise ValueError('同一评委对同一文章重复评分')
        seen.add(key)
        info = mapping[article]
        for metric in METRICS:
            raw = str(row.get(metric, '') or '').strip()
            if not raw:
                missing.append({'reviewer_id':reviewer,'article_id':article,'metric':metric})
                continue
            try:
                score = float(raw)
            except ValueError as error:
                raise ValueError('评分必须为1至5整数或留空') from error
            if not math.isfinite(score) or score not in (1,2,3,4,5):
                raise ValueError('评分必须为1至5整数或留空')
            values[(info['task_id'], info['group'], metric)][reviewer] = score
    absent_rows = [{'reviewer_id':r,'article_id':a} for r in reviewers for a in mapping if (r,a) not in seen]
    summaries = {}
    pairs = {}
    for metric in METRICS:
        summaries[metric] = {}
        for group in groups:
            task_means = [statistics.mean(scores.values()) for (task,g,m),scores in values.items() if g==group and m==metric and scores]
            summaries[metric][group] = {'tasks':len(task_means),'mean':statistics.mean(task_means) if task_means else None}
        for group in [g for g in groups if g!='A'] if 'A' in groups else []:
            differences, complete, unmatched = [], [], []
            for task in sorted({item['task_id'] for item in mapping.values()}):
                base, tested = values.get((task,'A',metric),{}),values.get((task,group,metric),{})
                shared = set(base)&set(tested)
                if not shared:
                    unmatched.append(task)
                    continue
                differences.append(statistics.mean(tested[r]-base[r] for r in shared))
                complete.append({'task_id':task,'paired_reviewers':len(shared)})
            pairs[group+'-A/'+metric] = {'task_count':len(differences),
                'mean_difference':statistics.mean(differences) if differences else None,
                'ci95':clustered_ci(differences,repetitions,seed), 'task_pairs':complete,'missing_task_pairs':unmatched}
    return {'status':'scored_partial' if values and (missing or absent_rows) else 'scored_complete' if values else 'awaiting_human_scores',
        'groups':list(groups),'controls':mapping_data.get('controls',{}),
        'scope':'练习结果不作真实质量证明；真实研究需核实实验控制和独立人评。人工评分先在同任务同组内平均；配对差异仅使用相同评委，置信区间按任务聚类重采样，不将多名评委当独立任务。',
        'bootstrap':{'unit':'task','repetitions':repetitions,'seed':seed,'method':'paired task percentile 95%; fewer than two tasks => null'},
        'group_summaries':summaries,'paired_comparisons':pairs,'missing_cells':missing,'missing_rows':absent_rows}


def classification(rows):
    valid, missing = [], []
    for index, row in enumerate(rows, 2):
        gold, pred = row.get('gold','').strip(),row.get('predicted','').strip()
        if not gold or not pred:
            missing.append(index)
            continue
        if gold not in LABELS or pred not in LABELS:
            raise ValueError('结构标签必须属于七类标签')
        valid.append((gold,pred))
    if not valid:
        return {'status':'awaiting_annotations','rows':0,'macro_f1':None,'per_label':{},'missing_rows':missing}
    metrics = {}
    for label in LABELS:
        tp=sum(g==label and p==label for g,p in valid)
        fp=sum(g!=label and p==label for g,p in valid)
        fn=sum(g==label and p!=label for g,p in valid)
        precision=tp/(tp+fp) if tp+fp else 0.0
        recall=tp/(tp+fn) if tp+fn else 0.0
        metrics[label]={'precision':precision,'recall':recall,'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.,'support':tp+fn}
    return {'status':'evaluated_partial' if missing else 'evaluated','rows':len(valid),
        'macro_f1':statistics.mean(m['f1'] for m in metrics.values()),
        'macro_policy':'固定七类标签等权平均；无真实/预测样本类别F1=0，逐类support必须一同报告。',
        'per_label':metrics,'missing_rows':missing}


def structure_metrics(rows):
    seen=set()
    for row in rows:
        key=(row.get('article_id','').strip(),row.get('paragraph_id','').strip())
        if all(key):
            if key in seen:
                raise ValueError('同一文章段落重复标注，不能重复计数')
            seen.add(key)
    report=classification(rows)
    paired=[]
    missing=[]
    for index,row in enumerate(rows,2):
        a,b=row.get('annotator1','').strip(),row.get('annotator2','').strip()
        if not a or not b:
            missing.append(index)
            continue
        if a not in LABELS or b not in LABELS:
            raise ValueError('人工标注标签无效')
        paired.append((a,b))
    kappa=None
    if paired:
        count=len(paired)
        observed=sum(a==b for a,b in paired)/count
        ca,cb=Counter(a for a,b in paired),Counter(b for a,b in paired)
        expected=sum(ca[label]*cb[label] for label in LABELS)/(count*count)
        kappa=(observed-expected)/(1-expected) if expected<1 else None
    report['agreement']={'paired_items':len(paired),'cohen_kappa':kappa,'missing_rows':missing,
                         'scope':'两人独立标注的一致性，不代表模型准确率；无配对或期望一致率为1时kappa不可定义。'}
    report['domains']={domain:classification([r for r in rows if r.get('domain','').strip()==domain])
                       for domain in sorted({r.get('domain','').strip() for r in rows if r.get('domain','').strip()})}
    return report


def templates(output):
    output=Path(output)
    write_json(output/'articles-input-template.json',{'controls':{'model_version':'待填写','source_snapshot':'待填写','word_budget':'待填写','cost_cap':'待填写'},'tasks':[]})
    write_csv(output/'structure-annotations-template.csv',('article_id','paragraph_id','domain','gold','predicted','annotator1','annotator2'),[])
    write_json(output/'human-scores-status.json',{'status':'awaiting_articles_and_human_scores','scope':'尚未导入真实文章或真人评分，不产生任何效果分数。'})
    (output/'使用说明.md').write_text('''# 离线评价工具\n\n当前仅提供空模板，没有真实评分或模型质量结果。\n\n文章JSON的 tasks 每项：task_id、brief、articles；articles默认恰好五项，每项含 group（A/B/C/D/E）和 text。若预注册只做A/E两组，使用 --groups A E；四稿流程练习使用 --groups A B C D。每个任务必须完整包含所声明的全部组，不可把缺组当作已完成五组实验。练习结果不作真实质量证明。A原版、B仅需求规划、C仅主动补料、D仅结构迁移、E全部。各组素材、模型、篇幅及费用控制由研究者核实并在controls记录，工具不能自动证明实验公平。请把相同事实核对资料纳入brief或另行提供，勿在正文/brief标注组名或算法。\n\n运行 scripts/sprint_evaluation.py blind --input 文章.json --output 新目录 --reviewers 3。分别分发reviewers下每名评委文件夹，绝不分发researcher-private。CSV五项是完整性、事实准确性、连贯性、自然度、使用价值，填1–5整数；未评分留空。外部表格软件保存UTF-8 CSV。\n\n运行 scores --mapping 新目录/researcher-private/mapping.json --csv 各评委scores.csv（可多个） --output 评分报告.json。任务为配对和bootstrap独立单位，少于两个配对任务不提供CI；缺失评分和未提交行全部列出。不同组只对共同评委配对，不能把更多评委当更多任务。报告中的空值不是0分。\n\n结构标注CSV使用七类 HOOK/PROBLEM/CONTEXT/EVIDENCE/SOLUTION/WARNING/CTA；gold为独立裁定金标，predicted为程序预测，annotator1/annotator2须两人独立标注，不能复制预测充当人工金标。运行 structure --csv 标注.csv --output 结构报告.json；输出固定七类Macro-F1、逐类Precision/Recall/F1、support、分领域指标及Cohen kappa。空表无分数，未填行列出，不代表通过。相同段落不得重复录入。\n\n所有命令在app目录运行；只在离线数据上计算，不调用模型或网络。\n''',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    form=sub.add_parser('templates');form.add_argument('--output',required=True)
    blind=sub.add_parser('blind');blind.add_argument('--input',required=True);blind.add_argument('--output',required=True);blind.add_argument('--reviewers',type=int,default=3);blind.add_argument('--seed',type=int,default=20261102);blind.add_argument('--groups',nargs='+',choices=GROUPS,default=list(GROUPS))
    scores=sub.add_parser('scores');scores.add_argument('--mapping',required=True);scores.add_argument('--csv',nargs='+',required=True);scores.add_argument('--output',required=True);scores.add_argument('--bootstrap',type=int,default=5000);scores.add_argument('--seed',type=int,default=20261102)
    structure=sub.add_parser('structure');structure.add_argument('--csv',required=True);structure.add_argument('--output',required=True)
    args=parser.parse_args()
    try:
        if args.command=='templates':templates(args.output)
        elif args.command=='blind':
            result=blind_package(json.loads(Path(args.input).read_text(encoding='utf-8')),args.output,args.reviewers,args.seed,args.groups)
            print(json.dumps(result,ensure_ascii=False))
        elif args.command=='scores':
            result=aggregate_scores(json.loads(Path(args.mapping).read_text(encoding='utf-8')),[r for file in args.csv for r in read_csv(file)],args.bootstrap,args.seed)
            write_json(args.output,result)
        else:write_json(args.output,structure_metrics(read_csv(args.csv)))
    except (ValueError,KeyError,TypeError) as error:
        parser.error(str(error))


if __name__=='__main__':main()

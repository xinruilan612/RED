#!/usr/bin/env python3
"""Publish frozen study receipts and blank independent reviews; no model or network."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from scripts.sprint_evaluation import blind_package
from scripts.build_review_practice import RUBRIC,FORM
from scripts.package_teacher import secret_candidates

PRIVATE={'owner','owner_id','account_id','connection_id','api_key','password','cookie','csrf',
         'authorization','secret','credentials','credential','access_token','refresh_token'}


def sha(data):return hashlib.sha256(data).hexdigest()


def sanitize(value):
    if isinstance(value,dict):return {key:'[已隐去]' if key.lower() in PRIVATE else sanitize(item) for key,item in value.items()}
    if isinstance(value,list):return [sanitize(item) for item in value]
    return value


def write_public(path,value):
    text=json.dumps(sanitize(value),ensure_ascii=False,indent=2)+'\n'
    if secret_candidates('published-study.json',text.encode()):raise ValueError('Public evidence secret scan failed')
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8')
    return sha(text.encode())


def build_report(receipts,dataset,public,blind,source_commit='6f925cf',reviewers=3):
    receipts,dataset,public,blind=map(Path,(receipts,dataset,public,blind))
    summary_raw=(receipts/'summary.json').read_bytes();summary=json.loads(summary_raw)
    write_public(public/'frozen_summary.json',summary)
    data_raw=dataset.read_bytes();data=json.loads(data_raw)
    tasks={row['id']:row for row in data.get('items',data.get('tasks',[]))}
    design=summary['experiment'];registered=design['task_ids'];groups=design['groups']
    if groups!=['A','E']:raise ValueError('本报告要求预注册A/E两组')
    if set(registered)-set(tasks):raise ValueError('缺少预注册任务')
    expected_hash=design.get('provenance',{}).get('dataset_sha256')
    if expected_hash and expected_hash!=sha(data_raw):raise ValueError('数据文件与实跑冻结hash不一致')
    cases={row['id']:row for row in summary.get('cases',[])}
    if len(cases)!=len(summary.get('cases',[])):raise ValueError('实跑case重复')
    rows=[];snapshots={};receipt_hashes={};known_new=0;previous=summary['initial_upper_micro']
    for task_id in registered:
        for group in groups:
            case_id=task_id+'-'+group;case=cases.get(case_id)
            if case is None:
                rows.append({'id':case_id,'task_id':task_id,'group':group,'status':'not_run_after_safety_stop',
                             'model_calls':0,'elapsed_seconds':None,'title_characters':None,'body_characters':None,
                             'word_budget':tasks[task_id].get('input',tasks[task_id])['creation'].get('word_count'),
                             'known_upper_micro':0,'unknown_reserved_micro':0})
                continue
            file=receipts/(case_id+'.json')
            if file.is_symlink() or not file.is_file():raise ValueError('缺少安全receipt: '+case_id)
            raw=file.read_bytes();receipt=sanitize(json.loads(raw));calls=receipt.get('calls',[])
            tokens=sum(call['tokens'] for call in calls if type(call.get('tokens')) is int)
            known=tokens*8;known_new+=known
            incremental=case['cumulative_upper_micro']-previous;previous=case['cumulative_upper_micro']
            reserve=max(0,incremental-known)
            unknown=[call for call in calls if call.get('tokens') is None and call.get('status')!='not_sent']
            drafts=receipt.get('drafts',[]);content=drafts[-1]['content'] if drafts else {}
            finished=bool(case.get('completed') and drafts)
            status='draft_ready_human_review_pending' if finished else 'failed_unknown_usage' if unknown else 'incomplete'
            row={'id':case_id,'task_id':task_id,'group':group,'status':status,
                 'model_calls':len(calls),'unknown_calls':len(unknown),'elapsed_seconds':case.get('elapsed_seconds'),
                 'title_characters':len(content.get('selected_title','')) if drafts else None,
                 'body_characters':len(content.get('body','')) if drafts else None,
                 'cta_characters':len(content.get('cta','')) if drafts else None,
                 'word_budget':tasks[task_id].get('input',tasks[task_id])['creation'].get('word_count'),
                 'known_upper_micro':known,'unknown_reserved_micro':reserve,
                 'review_decision':(receipt.get('review') or {}).get('decision'),
                 'call_statuses':[{'stage':call.get('stage'),'status':call.get('status'),'error':call.get('error')} for call in calls],
                 'prompt_versions':sorted({call['prompt_version'] for call in calls if call.get('prompt_version')}),
                 'model_versions':sorted({str(call.get('provider'))+'/'+str(call.get('model')) for call in calls}),
                 'input_hashes':sorted({call['input_hash'] for call in calls if call.get('input_hash')})}
            rows.append(row);snapshots[case_id]=receipt
            public_hash=write_public(public/'receipts'/(case_id+'.json'),receipt)
            receipt_hashes[case_id]={'source_sha256':sha(raw),'public_sha256':public_hash}
    if set(cases)-{row['id'] for row in rows}:raise ValueError('发现未预注册的case，拒绝丢弃')
    total=summary['cumulative_upper_micro'];initial=summary['initial_upper_micro']
    unknown_upper=total-initial-known_new
    if unknown_upper<0:raise ValueError('费用与冻结摘要不一致')
    paired=[task_id for task_id in registered if all(next(row for row in rows if row['id']==task_id+'-'+g)['status']=='draft_ready_human_review_pending' for g in groups)]
    result={'schema_version':1,'source_commit':source_commit,'scope':summary['scope'],
            'data_kind':'public-source-constructed','is_user_submission':False,'has_human_quality_scores':False,
            'registered_tasks':registered,'registered_groups':groups,'registered_cells':len(rows),
            'draft_cells':sum(row['status']=='draft_ready_human_review_pending' for row in rows),
            'complete_paired_tasks':paired,'failed_cells':sum(row['status'].startswith('failed') for row in rows),
            'not_run_cells':sum(row['status']=='not_run_after_safety_stop' for row in rows),
            'stop_reason':summary.get('stop_reason'),'cases':rows,
            'cost_upper_micro':{'previous_cumulative':initial,'known_new':known_new,'unknown_reserved':unknown_upper,
                                'new_conservative_total':total-initial,'known_cumulative':initial+known_new,'conservative_cumulative':total},
            'cost_scope':'按每Token 8微元的已核对保守上界折算；未知用量继续保留预留，不是供应商实际账单。',
            'provenance':{'dataset_sha256':sha(data_raw),'summary_source_sha256':sha(summary_raw),
                          'receipt_hashes':receipt_hashes,'experiment':design},
            'quality_conclusion':None,'quality_status':'awaiting_independent_blind_reviews',
            'warnings':['模型approved不代表事实已独立核实；needs_human保留待核查意见。',
                        '正文字符按Python Unicode码点计数，CTA单列，不含标签，不与token混用。',
                        '只对已完成的三对六稿组织盲评，保留所有预注册失败/未运行格，不能作为六任务全部完成。']}
    write_public(public/'run_summary.json',result)
    lines=['# 官方公开资料构造任务：真实模型执行记录','',
        '这是研究者根据官方公开资料构造的任务，使用真实模型运行；不是真实用户投稿，也不是创作者试用反馈。',
        '尚无独立人工评分，不报告文章质量提升。模型审核approved不等于独立事实核实。所有失败和未运行格保留。','',
        '源码冻结：`'+source_commit+'`。预注册'+str(len(registered))+'任务×A/E两组，共'+str(len(rows))+'格；本轮按安全停止规则保留部分完成。','',
        '|任务组|执行状态|模型调用|秒|标题字符|正文字符|期望字数|已知费用上界/元|未知预留/元|',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    labels={'draft_ready_human_review_pending':'已有成稿，待独立人审','failed_unknown_usage':'失败，用量未知，已停机','not_run_after_safety_stop':'安全停止后未运行','incomplete':'未完成'}
    for row in rows:
        val=lambda key:'—' if row.get(key) is None else str(row[key])
        lines.append('|'+ '|'.join([row['id'],labels[row['status']],str(row['model_calls']),val('elapsed_seconds'),val('title_characters'),val('body_characters'),val('word_budget'),f"{row['known_upper_micro']/1e6:.6f}",f"{row['unknown_reserved_micro']/1e6:.6f}"])+'|')
    costs=result['cost_upper_micro']
    lines += ['',f"此前累计 {initial/1e6:.6f} 元；本轮已知用量费用上界 {known_new/1e6:.6f} 元；未知用量保留 {unknown_upper/1e6:.6f} 元。",
              f"累计已知上界 {costs['known_cumulative']/1e6:.6f} 元；累计保守上界 {total/1e6:.6f} 元；本轮保守新增 {(total-initial)/1e6:.6f} 元。",'',result['cost_scope'],'',
              '用量未知失败：'+ '、'.join(row['id'] for row in rows if row['status']=='failed_unknown_usage')+'；没有自动重试。后续'+str(result['not_run_cells'])+'格停止，绝不将未运行记成成功。',
              '存在invalid调用的任务：'+'、'.join(row['id'] for row in rows if any(call['status']=='invalid' for call in row.get('call_statuses',[])))+'；保留原始问题与保守人工交接，不能写成审核全部通过。','',
              '每个公开receipt保留call的prompt_version、input_hash、来源hash及审核记录；输入与脱敏输出SHA256见run_summary.json。',
              '完整配对进入三位独立评委盲评目录。开发者自评须单列，不能混入reviewer-01至03的独立评分；空白保持未评分。']
    (public/'RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    blind_tasks=[]
    for task_id in paired:
        task=tasks[task_id];initial_input=task.get('input',task)
        brief=initial_input['topic']+'\n目标读者：'+initial_input['audience']+'\n篇幅要求：'+str(initial_input['creation'].get('word_count'))+'字\n本次给定事实：\n'+initial_input['material']
        brief+='\n核对口径：只以给定事实核对；未知保留未知。公开链接是来源，不表示评委已独立读完全文。'
        articles=[]
        for group in groups:
            content=snapshots[task_id+'-'+group]['drafts'][-1]['content']
            articles.append({'group':group,'text':content['selected_title']+'\n\n'+content['body']+'\n\n'+content.get('cta','')+'\n\n'+' '.join('#'+tag for tag in content.get('tags',[]))})
        blind_tasks.append({'task_id':task_id,'brief':brief,'articles':articles})
    if not blind_tasks:raise ValueError('没有完整配对成稿，不能生成盲评包')
    blind_result=blind_package({'purpose':'independent_blind_review_pending','controls':{'data_kind':'public-source-constructed','source_commit':source_commit,'partial_completion':True,'no_user_submission':True},'tasks':blind_tasks},blind,reviewers=reviewers,groups=('A','E'))
    mapping_path=blind/'researcher-private/mapping.json'
    mapping=json.loads(mapping_path.read_text())
    mapping['scope']='研究者持有的独立盲评分组映射，不向评委分发；当前无评分，不能报告质量提升。'
    mapping_path.write_text(json.dumps(mapping,ensure_ascii=False,indent=2),encoding='utf-8')
    (blind/'分发说明.md').write_text('只把每位reviewer对应的“独立评审.zip”分别发给该评委。不要发送整个目录或researcher-private分组映射。\n\n独立评委先阅读事实简报与评分标准，逐篇填写，下载评分CSV交回；未核对项留空。开发者若自评，使用单独developer-self记录，不能复用reviewer-01至03身份或混入独立汇总。本轮是公开资料构造任务的三对六稿部分批次；预注册另有一次失败和五格未运行，完整状态见正式报告。\n',encoding='utf-8')
    for folder in sorted((blind/'reviewers').iterdir()):
        page=folder/'articles.html';text=page.read_text()
        intro='<h1>公开资料构造任务：独立文章盲评</h1><p>'+str(len(paired))+'项任务共'+str(len(paired)*2)+'篇真实模型稿，组别隐藏。不是用户投稿或虚构产品测试；源自官方公开资料的研究者构造任务。只评价本次给定事实，未核对项留空。开发者不得作为独立评委计入本表。</p>'
        rubric=RUBRIC.replace('虚构任务只核对给定资料，不证明现实商品真实性。','公开资料构造任务只按给定事实核对；来源链接不表示已独立核实所有现实条件。')
        text=text.replace('<h1>文章评价</h1>',intro).replace('<article>',rubric+'<article>',1)
        text+=FORM.replace('__REVIEWER__',json.dumps(folder.name))
        page.write_text(text,encoding='utf-8')
        with zipfile.ZipFile(blind/(folder.name+'-独立评审.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(folder.iterdir()):archive.write(file,arcname=file.name)
        with zipfile.ZipFile(blind/(folder.name+'-独立评审.zip')) as archive:
            if archive.testzip() or any('mapping' in name or 'private' in name for name in archive.namelist()):raise ValueError('评委zip隔离检查失败')
    write_public(public/'blind_review_status.json',{'status':'awaiting_independent_scores','paired_tasks':paired,'articles':len(paired)*2,'reviewers':reviewers,'mapping_not_for_reviewers':True,'quality_improvement':None})
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipts',type=Path,required=True);parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--public',type=Path,required=True);parser.add_argument('--blind',type=Path,required=True)
    parser.add_argument('--source-commit',default='6f925cf');args=parser.parse_args()
    result=build_report(args.receipts,args.dataset,args.public,args.blind,args.source_commit)
    print(json.dumps({key:result[key] for key in ('registered_cells','draft_cells','failed_cells','not_run_cells','cost_upper_micro')},ensure_ascii=False))


if __name__=='__main__':main()

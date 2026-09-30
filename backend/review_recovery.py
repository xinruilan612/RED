"""Free, conservative recovery of received review format failures; never approval."""
import copy
import json
import time
from dataclasses import asdict
from datetime import datetime
from uuid import uuid4

from backend.contracts import DomainError, require
from backend.live import draft_text, material_records, normalize, review_gates, verify_quotes
from backend.workflow import Run, digest


def candidate(db, store, run):
    require(run.workflow_type=='creation' and run.context.get('mode')=='live' and
            run.run_status=='RUNNING' and run.current_stage=='reviewer' and run.drafts and not run.review,
            'INVALID_TRANSITION','当前没有可处理的审核结果')
    job=db.execute('SELECT status FROM runtime_jobs WHERE run_id=?',(run.run_id,)).fetchone()
    require(not job or job[0] not in ('queued','running','pausing'),'JOB_ACTIVE','后台任务尚未停稳，请稍后重试')
    require(not db.execute("SELECT 1 FROM live_steps WHERE run_id=? AND state='running'",(run.run_id,)).fetchone(),
            'JOB_ACTIVE','同步调用尚未结束')
    row=db.execute(f'''SELECT c.id,c.state,c.response_json,c.actual,a.snapshot_id,a.started
        FROM live_calls c LEFT JOIN model_audit a ON a.call_id=c.id
        WHERE c.run_id=? AND c.stage='review' ORDER BY c.{store.order_column} DESC LIMIT 1''',(run.run_id,)).fetchone()
    require(row and row[1]=='invalid' and row[2] and row[3] is not None and row[4]==run.snapshot_id,
            'INVALID_TRANSITION','没有同一快照的已结算审核结果')
    draft=run.drafts[-1]
    created=next((e['occurred_at'] for e in reversed(run.events)
                  if e['type']=='artifact.created' and e['payload'].get('artifact_ref')==draft['ref']),None)
    require(created and row[5] is not None and row[5]>=datetime.fromisoformat(created).timestamp(),
            'VERSION_CONFLICT','审核结果早于当前稿件')
    raw=json.loads(row[2])
    error_kind=None
    try:normalize(run,'review',copy.deepcopy(raw))
    except DomainError as error:
        error_kind=str(error)
        require(error_kind in ('模型引用无法匹配原始素材','旧问题必须逐项复核'),'INVALID_TRANSITION','此审核错误不能自动整理，请查看诊断')
    else:raise DomainError('INVALID_TRANSITION','审核不存在可整理的格式错误')
    if error_kind=='旧问题必须逐项复核':
        clean=copy.deepcopy(raw)
        required={i['issue_id'] for i in (run.prior_review or {}).get('issues',[])}
        results=clean.get('previous_issue_results',[])
        require(isinstance(results,list) and all(isinstance(i,dict) for i in results),'INVALID_TRANSITION','复核列表格式无效')
        ids=[i.get('issue_id') for i in results]
        require(all(isinstance(i,str) for i in ids) and len(ids)==len(set(ids)) and required.issubset(ids),
                'INVALID_TRANSITION','缺少或重复本轮旧问题，不能推定复核结果')
        historical={i['issue_id'] for report in run.reviews for i in report.get('issues',[])}
        excluded=[i for i in results if i['issue_id'] not in required]
        require(excluded and all(i['issue_id'] in historical and i.get('result') in ('resolved','unresolved','regressed') for i in excluded),
                'INVALID_TRANSITION','未知历史问题编号，不能自动整理')
        require(clean.get('decision') in ('revision_required','needs_human'),'INVALID_TRANSITION','整理格式不能自动通过审核')
        clean['previous_issue_results']=[i for i in results if i['issue_id'] in required]
        report=normalize(run,'review',clean)
        return row[0],report,[],excluded
    clean=copy.deepcopy(raw);kept=[];removed=[]
    for entry in clean['claim_map']:
        try:verify_quotes([entry],material_records(run.context),draft_text(draft['content']))
        except DomainError as error:
            require(str(error)=='模型引用无法匹配原始素材','INVALID_TRANSITION','稿件引用位置也不匹配，不能自动整理')
            require(isinstance(entry.get('excerpt'),str) and entry['excerpt'].strip() and entry['excerpt'] in draft_text(draft['content']),
                    'INVALID_TRANSITION','稿件引用位置也不匹配，不能自动整理')
            removed.append(entry)
        else:kept.append(entry)
    require(removed,'INVALID_TRANSITION','没有可整理的引用问题')
    clean['claim_map']=kept
    clean['decision']='revision_required';clean['next_action']='revise'
    require(isinstance(clean.get('issues'),list) and isinstance(clean.get('limitations'),list),'MODEL_OUTPUT_INVALID','审核字段无效')
    issue_id='citation-recovery-'+row[0]
    require(not any(i.get('issue_id')==issue_id for i in clean['issues'] if isinstance(i,dict)),'MODEL_OUTPUT_INVALID','恢复问题编号冲突')
    clean['issues'].append({'issue_id':issue_id,'severity':'major','state':'open','location':'body',
        'excerpt':removed[0]['excerpt'],'reason':f'{len(removed)} 条审核来源引用无法在素材正文中找到，尚未证明相关陈述有依据。',
        'suggestion':'请查看被排除的引用，核对原文并修改相关陈述；保存新版本后重新审核。'})
    clean['limitations'].append(f'本审核由已收到的结果免费整理：排除 {len(removed)} 条无效来源引用，保留原始响应审计；未通过审核，须人工改稿并重新审核。')
    report=normalize(run,'review',clean)
    return row[0],report,removed,[]


def public(store, run):
    try:
        with store.connect() as db:call_id,report,removed,excluded=candidate(db,store,run)
        return {'available':True,'call_id':call_id,'invalid_quotes':removed,'excluded_previous_results':excluded,
                'reason':('复审混入更早轮次的问题编号。可免费整理已收到的审核，保留本轮未解决问题；不会确认稿件或调用 AI。' if excluded else '稿件已保存，审核引用校验失败。可免费查看问题并进入改稿；不会确认稿件或调用 AI。')}
    except (DomainError,TypeError,ValueError,KeyError):return {'available':False}


def repair(store, run_id, owner, version, key):
    fingerprint=digest({'version':version,'action':'repair_review','payload':{}})
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        run=store._get(db,run_id,owner)
        old=db.execute('SELECT hash,response FROM commands WHERE run_id=? AND key=?',(run_id,key)).fetchone()
        if old:
            require(old[0]==fingerprint,'IDEMPOTENCY_CONFLICT','幂等键已用于其他命令')
            return Run(**json.loads(old[1]))
        require(run.status_version==version,'VERSION_CONFLICT','任务已更新，请刷新')
        call_id,report,removed,excluded=candidate(db,store,run)
        run.reviewed(report,review_gates(run,report))
        run.node_runs.append({'id':str(uuid4()),'agent':'reviewer','stage':'review','mode':'live',
            'snapshot_id':run.snapshot_id,'input':{'recovered_call_id':call_id,'excluded_claim_map':removed,'excluded_previous_results':excluded},
            'output':report,'model_calls':0,'tokens':0,'cost':0,'duration_ms':0,'tools':[],
            'memory':'人工触发免费整理已有审核；原始调用响应和费用保持不变'})
        run.event('agent.completed',agent='reviewer',stage='review',mode='live',
                  recovery='obsolete_previous_issue_ids' if excluded else 'invalid_citations_for_manual_edit',
                  call_id=call_id,excluded_claim_map=removed,excluded_previous_results=excluded)
        db.execute("UPDATE runtime_jobs SET status=?,error=NULL,token=NULL,lease_until=NULL,thread_id=?,updated=? WHERE run_id=?",
                   ('waiting' if run.run_status=='WAITING_USER' else 'paused',str(uuid4()),time.time(),run_id))
        run.status_version+=1
        encoded=json.dumps(asdict(run),ensure_ascii=False)
        db.execute('UPDATE runs SET payload=? WHERE id=?',(encoded,run_id))
        db.execute('INSERT INTO commands VALUES(?,?,?,?)',(run_id,key,fingerprint,encoded))
        return run

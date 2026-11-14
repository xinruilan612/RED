"""Free, conservative recovery of received review format failures; never approval."""
import copy
import json
import time
from dataclasses import asdict
from datetime import datetime
from uuid import uuid4

from backend.contracts import DomainError, require
from backend.live import draft_text, normalize, retrieved_references, review_gates, schema
from backend.workflow import Run, digest


def conservative_review(run, raw, error):
    """Build a system handoff, never pretend an invalid response was a review.

    The caller must first prove settlement and binding to the current snapshot
    and draft. No persistence, model calls, raw response edits or text inference
    happen here. Even non-object responses can hand the existing draft to a human.
    """
    require(run.workflow_type=='creation' and run.drafts,
            'INVALID_TRANSITION','没有可交给人工核对的创作稿件')
    reason=str(error).strip()[:1000] or '模型审核结果格式或证据校验未通过'
    clean=schema('review')
    clean.update(decision='needs_human',next_action='request_human',claim_map=[],
        checks=[{**check,'result':'unknown','basis':'已收到的模型审核未通过校验；本项没有可接受的审核结论，需人工检查。'}
                for check in clean['checks']],
        limitations=['系统保守交接：已收到的审核未通过校验（'+reason+'）。原始响应保留在调用审计；此报告不代表模型已完成审核。',
                     '无效审核中的引用与定位未作为有效证据采用；系统没有补写或近似匹配来源、稿件文字。'],
        human_questions=['请逐项核对当前稿件与实际来源、原创性及既有问题；补充资料或保存修改后重新审核。'])
    # Existing issues remain unresolved by default; this is a conservative state
    # carryover, explicitly not a fabricated claim about the model's re-review.
    prior=(run.prior_review or {}).get('issues',[])
    clean['issues']=[{**copy.deepcopy(issue),'state':'open'} for issue in prior]
    clean['previous_issue_results']=[{'issue_id':issue['issue_id'],'result':'unresolved'} for issue in prior]
    if prior:clean['limitations'].append('既有问题由系统保守保留为未解决；模型未提供可靠的逐项复核结果。')
    research=run.branches.get('research')
    data=research.get('data') if isinstance(research,dict) else None
    if not isinstance(data,dict) or type(data.get('core_gap')) is not bool:
        clean['limitations'].append('当前稿件没有可靠的研究分支结果，资料缺口状态未知；人工保留或恢复稿件不表示事实已核验。')
    clean['issues'].append({'issue_id':'review-handoff-'+str(uuid4()),'severity':'major','state':'open','location':'body',
        'excerpt':'模型未能提供有效审核结论（请对照完整稿件）','reason':reason,
        'suggestion':'请人工核对完整稿件；本条没有有效的模型稿件定位，不表示正文某一具体句已被核实。'})
    claims=raw.get('claim_map') if isinstance(raw,dict) else None
    if isinstance(claims,list) and any(isinstance(item,dict) and
            (not isinstance(item.get('excerpt'),str) or not item['excerpt'].strip() or
             item['excerpt'] not in draft_text(run.drafts[-1]['content'])) for item in claims):
        clean['issues'][-1]['excerpt']='模型未能定位陈述（请对照完整稿件）'
        clean['limitations'].append('部分模型摘录未在当前稿件中原样找到；原始摘录仅保留于调用审计，不冒充有效的稿件定位。')
    ids=[source['source_id'] for source in retrieved_references(run.context)]
    if ids:clean['limitations'].append('实际提供的参考 source_id：'+'、'.join(ids)+
        '；仅记录输入来源，未证明模型采用或完成比对，借鉴要点及本题改写差异需人工核对。')
    return normalize(run,'review',clean,conservative_handoff=True)


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
    try:normalize(run,'review',copy.deepcopy(raw))
    except DomainError as error:
        require(error.code in ('MODEL_OUTPUT_INVALID','REVIEW_GATE_FAILED'),
                'INVALID_TRANSITION','此审核错误不能自动整理，请查看诊断')
        error_kind=str(error)
    else:
        # The original review may have failed a later domain transition, after
        # schema normalization. Never turn an invalid persisted response into
        # approval just because its schema now passes.
        error_kind='已收到的审核未完成有效的领域校验，需人工核对'
    report=conservative_review(run,raw,error_kind)
    removed=copy.deepcopy(raw.get('claim_map',[])) if isinstance(raw,dict) else []
    if not isinstance(removed,list):removed=[]
    required={i['issue_id'] for i in (run.prior_review or {}).get('issues',[])}
    results=raw.get('previous_issue_results',[]) if isinstance(raw,dict) else []
    excluded=[copy.deepcopy(i) for i in results if isinstance(i,dict) and i.get('issue_id') not in required] if isinstance(results,list) else []
    return row[0],report,removed,excluded


def public(store, run):
    try:
        with store.connect() as db:call_id,report,removed,excluded=candidate(db,store,run)
        return {'available':True,'call_id':call_id,'invalid_quotes':removed,'excluded_previous_results':excluded,
                'reason':'稿件已保存，已收到的审核未能可靠校验。可免费保留原稿、已有问题和调用记录，交给人工核对；不会确认稿件或调用 AI。'}
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
            'memory':'人工触发保守交接；没有可靠的模型审核结论，原始调用响应和费用保持不变'})
        run.event('agent.completed',agent='reviewer',stage='review',mode='live',
                  recovery='system_conservative_handoff',
                  call_id=call_id,excluded_claim_map=removed,excluded_previous_results=excluded)
        db.execute("UPDATE runtime_jobs SET status=?,error=NULL,token=NULL,lease_until=NULL,thread_id=?,updated=? WHERE run_id=?",
                   ('waiting' if run.run_status=='WAITING_USER' else 'paused',str(uuid4()),time.time(),run_id))
        run.status_version+=1
        encoded=json.dumps(asdict(run),ensure_ascii=False)
        db.execute('UPDATE runs SET payload=? WHERE id=?',(encoded,run_id))
        db.execute('INSERT INTO commands VALUES(?,?,?,?)',(run_id,key,fingerprint,encoded))
        return run

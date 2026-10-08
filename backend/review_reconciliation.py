"""Explicit, free correction of a stored review decision; never user acceptance."""
import copy
import json
import time
from dataclasses import asdict
from uuid import uuid4

from backend.contracts import DomainError, require
from backend.live import review_gates
from backend.workflow import Run, digest


def candidate(db, store, run):
    require(run.workflow_type=='creation' and run.context.get('mode')=='live' and
            ((run.run_status=='RUNNING' and run.current_stage=='content') or
             (run.run_status=='WAITING_USER' and run.wait_reason=='revision_limit')) and
            not run.acceptance and not run.accepted_ref and run.drafts and run.review and
            run.review.get('decision')=='revision_required',
            'INVALID_TRANSITION','当前没有可重新判定的审核意见')
    job=db.execute('SELECT status FROM runtime_jobs WHERE run_id=?',(run.run_id,)).fetchone()
    require(not job or job[0] not in ('queued','running','pausing'),'JOB_ACTIVE','后台任务尚未停稳')
    require(not db.execute("SELECT 1 FROM live_steps WHERE run_id=? AND state='running'",(run.run_id,)).fetchone(),
            'JOB_ACTIVE','同步调用尚未结束')
    lineage=db.execute('SELECT budget_id FROM live_lineage WHERE run_id=?',(run.run_id,)).fetchone()
    root=lineage[0] if lineage else run.run_id
    require(not db.execute('SELECT 1 FROM live_calls WHERE (run_id=? OR run_id IN '
                           '(SELECT run_id FROM live_lineage WHERE budget_id=?)) AND actual IS NULL',
                           (run.run_id,root)).fetchone(),'UNKNOWN_USAGE','存在未结算调用，不能重新判定')
    draft=run.drafts[-1]; old=run.review
    require(old.get('draft_ref')==draft['ref'] and old.get('snapshot_id')==draft['snapshot_id']==run.snapshot_id
            and old.get('content_hash')==draft['content_hash']==digest(draft['content'])
            and run.reviews and run.reviews[-1]==old,
            'VERSION_CONFLICT','审核与当前稿件不匹配')
    from backend.review_policy import reconcile_optional_review
    report=reconcile_optional_review(copy.deepcopy(old),draft,review_gates(run,old),run.prior_review)
    require(report.get('decision')=='approved' and report.get('decision_adjustment'),
            'INVALID_TRANSITION','仍有必改问题或检查未通过，不能调整为待确认')
    report['ref']=str(uuid4())+'@1'
    report['reconciled_from']=old['ref']
    return report


def public(store,run):
    try:
        with store.connect() as db:report=candidate(db,store,run)
        return {'available':True,'review_ref':run.review['ref'],
                'reason':'必需检查已通过，仅余可选建议。可免费按审核规则重新判定，随后由你确认稿件；不调用 AI。'}
    except (DomainError,TypeError,ValueError,KeyError):return {'available':False}


def reconcile(store,run_id,owner,version,key):
    fingerprint=digest({'version':version,'action':'reconcile_review','payload':{}})
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        run=store._get(db,run_id,owner)
        old=db.execute('SELECT hash,response FROM commands WHERE run_id=? AND key=?',(run_id,key)).fetchone()
        if old:
            require(old[0]==fingerprint,'IDEMPOTENCY_CONFLICT','幂等键已用于其他命令')
            return Run(**json.loads(old[1]))
        require(run.status_version==version,'VERSION_CONFLICT','任务已更新，请刷新')
        report=candidate(db,store,run)
        if run.run_status=='WAITING_USER':
            run._transition('QUEUED');run._transition('RUNNING')
        run.current_stage='reviewer'
        run.reviewed(report,review_gates(run,report))
        run.node_runs.append({'id':str(uuid4()),'agent':'reviewer','stage':'review','mode':'live',
            'snapshot_id':run.snapshot_id,'input':{'reconciled_from':report['reconciled_from']},
            'output':copy.deepcopy(report),'model_calls':0,'tokens':0,'cost':0,'duration_ms':0,'tools':[],
            'memory':'用户触发免费审核规则重判；原报告、调用与费用不变，等待用户确认'})
        run.event('agent.completed',agent='reviewer',stage='review',mode='live',
                  recovery='optional_suggestions_decision_reconciliation',review_ref=report['ref'],
                  reconciled_from=report['reconciled_from'],model_calls=0)
        db.execute('UPDATE runtime_jobs SET status=?,error=NULL,token=NULL,lease_until=NULL,thread_id=?,updated=? WHERE run_id=?',
                   ('waiting',str(uuid4()),time.time(),run_id))
        run.status_version+=1
        encoded=json.dumps(asdict(run),ensure_ascii=False)
        db.execute('UPDATE runs SET payload=? WHERE id=?',(encoded,run_id))
        db.execute('INSERT INTO commands VALUES(?,?,?,?)',(run_id,key,fingerprint,encoded))
        return run

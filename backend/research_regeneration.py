"""Explicit fresh research snapshot; retain drafts, paid calls and all budgets."""
from copy import deepcopy
from backend.contracts import require
from backend.workflow import digest
from backend.web_research import selection


def prepare(db, run, data, job):
    require(run.workflow_type=='creation' and run.context.get('mode')=='live',
            'INVALID_TRANSITION','只有真实创作支持联网查证并重新生成')
    require(run.run_status in ('RUNNING','WAITING_USER') and
            (run.drafts or run.wait_reason in ('missing_material','hypothesis_permission')),
            'INVALID_TRANSITION','当前任务不能重新生成')
    require(not job or job[0] not in ('queued','running','pausing'),'JOB_ACTIVE','请先等待当前执行结束')
    require(not db.execute("SELECT 1 FROM live_steps WHERE run_id=? AND state='running'",(run.run_id,)).fetchone(),
            'STEP_ALREADY_ATTEMPTED','旧同步调用未决，需先核对')
    # Recovery descendants share the same budget and unresolved transport history.
    lineage=db.execute('SELECT budget_id FROM live_lineage WHERE run_id=?',(run.run_id,)).fetchone()
    budget_id=lineage[0] if lineage else run.run_id
    from backend.model_router import assert_recoverable_usage
    assert_recoverable_usage(db,budget_id)
    replacement=selection({'enabled':True,'queries':data.get('queries') or [run.context['topic'].strip()[:120]],
                           'provider':'bing','targets':['web']},'live')
    history=run.context.setdefault('research_regenerations',[])
    history.append(deepcopy({'snapshot_id':run.snapshot_id,'web_research':run.context.get('web_research'),
        'artifacts':run.artifacts,'branches':run.branches,'review':run.review,'prior_review':run.prior_review,
        'evidence':run.context.get('evidence',[]),'creation_retrieval':run.context.get('creation_retrieval')}))
    run.snapshot_id=digest({'previous':run.snapshot_id,'queries':replacement['queries'],'regeneration':len(history)})
    run.context['web_research']=replacement
    run.context['material_policy']='available_only'
    run.context['material_policy_version']='available-only-v1'
    run.context.pop('pending_revision',None)
    retrieval=run.context.get('creation_retrieval')
    if retrieval:
        for name, sources in retrieval['groups'].items():
            retrieval['groups'][name]=[s for s in sources if not s.get('source_id','').startswith('web:')]
        retrieval['sources']=[s for group in retrieval['groups'].values() for s in group]
        retrieval.pop('web_fact_filter',None)
        run.context['retrieval']=retrieval
        run.context['evidence']=retrieval['sources']
    else:
        run.context['evidence']=[s for s in run.context.get('evidence',[]) if not s.get('source_id','').startswith('web:')]
    run.artifacts=[];run.branches={};run.branch_errors={}
    run.review=None;run.prior_review=None;run.current_stage='brief'
    if run.run_status=='WAITING_USER':run._transition('QUEUED')

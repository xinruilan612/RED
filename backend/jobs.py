"""Durable job control. All ownership and lease fencing live in SQL transactions."""
import json
import time
from dataclasses import asdict
from uuid import uuid4
from backend.contracts import require, CONTRACT, PARAMETERS
from backend.schemas import JobCommand, parse
from backend.workflow import digest

ACTIVE = ('queued','running','pausing')


def graph_policy(run):
    require(run.workflow_type in ('creation','windtunnel'),'CONFIG_INVALID','未知工作流类型')
    expected = 'windtunnel.v1' if run.workflow_type=='windtunnel' else CONTRACT['runtime_extension']['graph_policy']
    require(run.context.get('graph_policy',expected)==expected,'CONFIG_INVALID','未知工作流执行策略')
    return expected


def next_creation_stage(run):
    if run.run_status == 'WAITING_USER':return 'human'
    if run.current_stage == 'brief':
        web=run.context.get('web_research',{})
        return 'web_research' if web.get('enabled') and web.get('status')!='complete' else 'brief'
    if run.current_stage == 'reviewer':return 'review'
    if run.review and run.review['decision']=='revision_required':return 'revise'
    return next(stage for stage in CONTRACT['content_stages'] if stage not in {a['stage'] for a in run.artifacts})


class Jobs:
    def __init__(self, store): self.store=store

    def command(self, owner, run_id, data):
        data=parse(JobCommand,data)
        if data.get('queries') is None:data.pop('queries',None)
        if data.get('feedback') is None:data.pop('feedback',None)
        require(data['action']=='revise_review' or 'feedback' not in data,'INVALID_INPUT','只有 AI 改稿可以提交修改意见')
        require(data['action']=='retry_research' or 'queries' not in data,'INVALID_INPUT','只有重新调查可以修改搜索词')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run=self.store._get(db,run_id,owner)
            policy=graph_policy(run)
            old=db.execute('SELECT fingerprint FROM runtime_commands WHERE run_id=? AND key=?',(run_id,data['key'])).fetchone()
            fingerprint=digest(data)
            if old:
                require(old[0]==fingerprint,'IDEMPOTENCY_CONFLICT','幂等键已用于其他命令')
                return
            require(run.status_version==data['version'],'VERSION_CONFLICT','任务已更新，请刷新')
            row=db.execute('SELECT status FROM runtime_jobs WHERE run_id=?',(run_id,)).fetchone()
            if data['action']=='revise_review':
                require(run.workflow_type=='creation','INVALID_INPUT','AI 改稿仅用于创作任务')
                require(not row or row[0] not in ACTIVE,'JOB_ACTIVE','任务已在后台执行')
                require(not db.execute("SELECT 1 FROM live_steps WHERE run_id=? AND state='running'",(run_id,)).fetchone(),'JOB_ACTIVE','同步调用尚未结束')
                require(not db.execute("SELECT 1 FROM live_calls WHERE run_id IN (SELECT run_id FROM live_lineage WHERE budget_id=(SELECT budget_id FROM live_lineage WHERE run_id=?)) AND actual IS NULL",(run_id,)).fetchone(),'USAGE_UNKNOWN','上次调用用量尚未确认，暂不重复请求')
                if not run.review:
                    from backend.review_recovery import apply_repair
                    apply_repair(db,self.store,run)
                require(run.run_status=='RUNNING' and run.current_stage=='content' and run.review and run.review['decision']=='revision_required','INVALID_TRANSITION','当前需要补充资料、人工确认或已达到改稿上限，请先处理提示')
                request={'snapshot_id':run.snapshot_id,'draft_ref':run.drafts[-1]['ref'],'feedback':data.get('feedback','').strip(),'review_ref':run.review['ref']}
                run.context['revision_request']=request
                run.context.setdefault('revision_requests',[]).append(request)
            if data['action'] in ('start','step','retry_research','revise_review'):
                require(run.run_status in ('QUEUED','RUNNING'),'INVALID_TRANSITION','请先完成人工操作')
                require(not db.execute("SELECT 1 FROM live_steps WHERE run_id=? AND state='running'",(run_id,)).fetchone(),'STEP_ALREADY_ATTEMPTED','旧同步调用未决，需先核对')
                require(not row or row[0] not in ACTIVE,'JOB_ACTIVE','任务已在后台执行')
                if row and row[0]=='blocked':
                    require(not db.execute("SELECT 1 FROM live_calls WHERE run_id IN (SELECT run_id FROM live_lineage WHERE budget_id=(SELECT budget_id FROM live_lineage WHERE run_id=?)) AND actual IS NULL",(run_id,)).fetchone(),
                            'USAGE_UNKNOWN','上次调用用量尚未确认，已保留进度；请先核对接口用量，暂不重复请求')
                from backend.review_recovery import public as recovery_public
                require(not recovery_public(self.store,run)['available'],'INVALID_TRANSITION','审核引用需要处理，请先点击免费查看审核问题并进入改稿')
                from backend.model_router import review_execution
                preflight=review_execution(db,run)
                require(not (preflight and preflight['blocked']),'STAGE_ATTEMPT_LIMIT',preflight['message'] if preflight else '复审次数已用完')
                if data['action'] in ('step','retry_research'):
                    require(run.workflow_type=='creation','INVALID_INPUT','逐步执行仅用于创作任务')
                if data['action']=='retry_research':
                    from backend.web_research import selection
                    web=run.context.get('web_research',{})
                    require(run.current_stage=='brief' and not run.branches and not run.node_runs and
                            not db.execute('SELECT 1 FROM live_calls WHERE run_id=?',(run_id,)).fetchone(),
                            'INVALID_TRANSITION','分析已开始，不能修改本次调查快照')
                    require(web.get('enabled') and web.get('status') in ('insufficient','searching'),
                            'INVALID_TRANSITION','只有失败或中断的联网调查可以重新搜索')
                    replacement=selection({'enabled':True,'queries':data.get('queries')},run.context.get('mode'))
                    run.context.setdefault('web_research_history',[]).append(web)
                    run.context['web_research']=replacement
                    run.snapshot_id=digest({'previous':run.snapshot_id,'queries':replacement['queries'],'retry':len(run.context['web_research_history'])})
                    # The old checkpoint may hold an interrupted tool cursor. Fresh graph,
                    # same durable run/budget, with the previous report retained above.
                    if row:db.execute('UPDATE runtime_jobs SET thread_id=? WHERE run_id=?',(str(uuid4()),run_id))
                run.context['runtime_execution']={'mode':'automatic' if data['action'] in ('start','revise_review') else 'step'}
                if data['action'] not in ('start','revise_review'):run.context['runtime_execution']['target']=next_creation_stage(run)
                if row:
                    db.execute("UPDATE runtime_jobs SET status='queued',error=NULL,token=NULL,lease_until=NULL,updated=? WHERE run_id=?",(time.time(),run_id))
                else:
                    db.execute('INSERT INTO runtime_jobs(id,run_id,owner,status,updated,thread_id,policy) VALUES(?,?,?,?,?,?,?)',(str(uuid4()),run_id,owner,'queued',time.time(),str(uuid4()),policy))
            else:
                require(row and row[0] in ACTIVE,'INVALID_TRANSITION','没有正在执行的后台任务')
                db.execute("UPDATE runtime_jobs SET status=CASE WHEN status='queued' THEN 'paused' ELSE 'pausing' END,updated=? WHERE run_id=?",(time.time(),run_id))
            run.status_version+=1
            db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(asdict(run),ensure_ascii=False),run_id))
            db.execute('INSERT INTO runtime_commands VALUES(?,?,?)',(run_id,data['key'],fingerprint))

    def claim(self, lease=CONTRACT['runtime_extension']['lease_s']):
        now=time.time()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            # Pausing work whose process died has no active provider transport to wait on.
            db.execute("UPDATE runtime_jobs SET status='paused',token=NULL WHERE status='pausing' AND lease_until<?",(now,))
            row=db.execute("SELECT id,run_id,owner,thread_id,policy FROM runtime_jobs WHERE status='queued' OR (status='running' AND lease_until<?) ORDER BY updated LIMIT 1",(now,)).fetchone()
            if not row:return None
            token=str(uuid4())
            db.execute("UPDATE runtime_jobs SET status='running',token=?,lease_until=?,updated=?,generation=generation+1 WHERE id=?",(token,now+lease,now,row[0]))
            return dict(zip(('id','run_id','owner','thread_id','policy'),row))|{'token':token}

    def guard(self, db, job, committing=False):
        row=db.execute('SELECT token,status,lease_until,elapsed FROM runtime_jobs WHERE id=?',(job['id'],)).fetchone()
        require(row and row[0]==job['token'] and row[2]>time.time(),'LEASE_LOST','Worker 租约已失效')
        require(row[3]<PARAMETERS['run_active_timeout_s'],'TIME_BUDGET','任务累计执行时间已到上限')
        require(row[1]=='running' or (committing and row[1]=='pausing'),'JOB_PAUSED','任务已暂停')
        run=self.store._get(db,job['run_id'],job['owner'])
        require(run.run_status not in ('SUCCEEDED','CANCELLED','FAILED','EXPIRED'),'RUN_STOPPED','任务已结束')
        return run

    def heartbeat(self, job, lease, elapsed):
        with self.store.connect() as db:
            db.execute('UPDATE runtime_jobs SET lease_until=?,elapsed=elapsed+? WHERE id=? AND token=? AND status IN (\'running\',\'pausing\')',(time.time()+lease,elapsed,job['id'],job['token']))

    def finish(self, job, status, error=None):
        with self.store.connect() as db:
            db.execute('UPDATE runtime_jobs SET status=?,error=?,token=NULL,lease_until=NULL,updated=? WHERE id=? AND token=?',(status,error,time.time(),job['id'],job['token']))

    def public(self, run_id, owner):
        with self.store.connect() as db:
            self.store._get(db,run_id,owner)
            row=db.execute('SELECT status,error,generation,updated,elapsed FROM runtime_jobs WHERE run_id=? AND owner=?',(run_id,owner)).fetchone()
            count=db.execute('SELECT COUNT(*) FROM runtime_nodes WHERE run_id=?',(run_id,)).fetchone()[0]
            worker=db.execute('SELECT MAX(heartbeat) FROM runtime_workers').fetchone()[0]
        return {'status':row[0] if row else 'idle','error':row[1] if row else None,'attempts':row[2] if row else 0,
                'updated':row[3] if row else None,'active_seconds':row[4] if row else 0,
                'completed_nodes':count,'worker_online':worker is not None and worker>time.time()-45}

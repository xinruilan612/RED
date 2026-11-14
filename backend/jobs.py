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
    if run.context.get('pending_revision') or (run.review and run.review['decision']=='revision_required'):return 'revise'
    return next(stage for stage in CONTRACT['content_stages'] if stage not in {a['stage'] for a in run.artifacts})


class Jobs:
    def __init__(self, store): self.store=store

    def command(self, owner, run_id, data):
        data=parse(JobCommand,data)
        if data.get('queries') is None:data.pop('queries',None)
        if data.get('references_only') is None:data.pop('references_only',None)
        require(data['action']=='retry_research' or 'references_only' not in data,'INVALID_INPUT','只有重新调查可以选择仅重读链接')
        require(data['action'] in ('retry_research','research_and_regenerate') or 'queries' not in data,'INVALID_INPUT','只有重新调查可以修改搜索词')
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
            if data['action']=='research_and_regenerate':
                from backend.research_regeneration import prepare
                prepare(db,run,data,row)
                if row:db.execute('UPDATE runtime_jobs SET thread_id=? WHERE run_id=?',(str(uuid4()),run_id))
            if (data['action']=='start' and run.workflow_type=='creation' and run.run_status=='WAITING_USER'
                    and run.wait_reason in ('missing_material','hypothesis_permission')):
                require(run.context.get('algorithm_questions_status') != 'pending',
                        'INVALID_TRANSITION', '请先回答或跳过关键问题')
                require(not row or row[0] not in ACTIVE,'JOB_ACTIVE','任务已在后台执行')
                require(not db.execute("SELECT 1 FROM live_steps WHERE run_id=? AND state='running'",(run_id,)).fetchone(),
                        'STEP_ALREADY_ATTEMPTED','旧同步调用未决，需先核对')
                previous_policy=run.context.get('material_policy','require_material')
                run.context['material_policy']='available_only'
                run.context['material_policy_version']='available-only-v1'
                run.context.setdefault('material_policy_changes',[]).append({
                    'from':previous_policy,'to':'available_only','version':'available-only-v1','trigger':'explicit_start','snapshot_id':run.snapshot_id})
                run._transition('QUEUED');run.start()
                if run.drafts:
                    require(run.review is not None,'INVALID_TRANSITION','当前审核记录缺失，请保留稿件并检查任务')
                    run._transition('WAITING_USER','final_confirmation')
                    if row:
                        db.execute("UPDATE runtime_jobs SET status='waiting',error=NULL,updated=? WHERE run_id=?",(time.time(),run_id))
                    run.status_version+=1
                    db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(asdict(run),ensure_ascii=False),run_id))
                    db.execute('INSERT INTO runtime_commands VALUES(?,?,?)',(run_id,data['key'],fingerprint))
                    return
                # Completed analysis is frozen evidence, not something to bill again.
                run.join(run.context.get('allow_hypothesis',False))
            if data['action'] in ('start','step','retry_research','research_and_regenerate'):
                require(run.run_status in ('QUEUED','RUNNING'),'INVALID_TRANSITION','请先完成人工操作')
                require(not db.execute("SELECT 1 FROM live_steps WHERE run_id=? AND state='running'",(run_id,)).fetchone(),'STEP_ALREADY_ATTEMPTED','旧同步调用未决，需先核对')
                require(not row or row[0] not in ACTIVE,'JOB_ACTIVE','任务已在后台执行')
                from backend.review_recovery import public as recovery_public
                require(not recovery_public(self.store,run)['available'],'INVALID_TRANSITION','审核引用需要处理，请先点击免费查看审核问题并进入改稿')
                if data['action'] in ('step','retry_research'):
                    require(run.workflow_type=='creation','INVALID_INPUT','逐步执行仅用于创作任务')
                if data['action']=='retry_research':
                    from backend.web_research import selection, reference_urls
                    web=run.context.get('web_research',{})
                    require(run.current_stage=='brief' and not run.branches and not run.artifacts and
                            (run.context.get('research_regenerations') or (not run.node_runs and
                            not db.execute('SELECT 1 FROM live_calls WHERE run_id=?',(run_id,)).fetchone())),
                            'INVALID_TRANSITION','分析已开始，不能修改本次调查快照')
                    require(web.get('enabled') and (web.get('status') in ('insufficient','searching') or
                            (web.get('status')=='complete' and reference_urls(run.context.get('material','')) and
                             not run.node_runs and not db.execute('SELECT 1 FROM live_calls WHERE run_id=?',(run_id,)).fetchone())),
                            'INVALID_TRANSITION','只有失败、中断或含参考链接且尚未开始分析的调查可以重新搜索')
                    replacement=selection({'enabled':True,'queries':data.get('queries'),
                        'provider':web.get('provider','bing'),'targets':web.get('targets',['web'])},run.context.get('mode'))
                    if data.get('references_only'):
                        require(reference_urls(run.context.get('material','')),'INVALID_INPUT','本次参考资料没有可重读的链接')
                        replacement['references_only']=True
                    run.context.setdefault('web_research_history',[]).append(web)
                    run.context['web_research']=replacement
                    run.snapshot_id=digest({'previous':run.snapshot_id,'queries':replacement['queries'],'retry':len(run.context['web_research_history'])})
                    # The old checkpoint may hold an interrupted tool cursor. Fresh graph,
                    # same durable run/budget, with the previous report retained above.
                    if row:db.execute('UPDATE runtime_jobs SET thread_id=? WHERE run_id=?',(str(uuid4()),run_id))
                automatic=data['action'] in ('start','research_and_regenerate')
                run.context['runtime_execution']={'mode':'automatic' if automatic else 'step'}
                if not automatic:run.context['runtime_execution']['target']=next_creation_stage(run)
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

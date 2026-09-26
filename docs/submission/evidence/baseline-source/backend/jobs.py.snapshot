"""Durable job control. All ownership and lease fencing live in SQL transactions."""
import json
import time
from dataclasses import asdict
from uuid import uuid4
from backend.contracts import require, CONTRACT, PARAMETERS
from backend.schemas import JobCommand, parse
from backend.workflow import digest

ACTIVE = ('queued','running','pausing')


class Jobs:
    def __init__(self, store): self.store=store

    def command(self, owner, run_id, data):
        data=parse(JobCommand,data)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run=self.store._get(db,run_id,owner)
            old=db.execute('SELECT fingerprint FROM runtime_commands WHERE run_id=? AND key=?',(run_id,data['key'])).fetchone()
            fingerprint=digest(data)
            if old:
                require(old[0]==fingerprint,'IDEMPOTENCY_CONFLICT','幂等键已用于其他命令')
                return
            require(run.status_version==data['version'],'VERSION_CONFLICT','任务已更新，请刷新')
            row=db.execute('SELECT status FROM runtime_jobs WHERE run_id=?',(run_id,)).fetchone()
            if data['action']=='start':
                require(run.run_status in ('QUEUED','RUNNING'),'INVALID_TRANSITION','请先完成人工操作')
                require(not db.execute("SELECT 1 FROM live_steps WHERE run_id=? AND state='running'",(run_id,)).fetchone(),'STEP_ALREADY_ATTEMPTED','旧同步调用未决，需先核对')
                require(not row or row[0] not in ACTIVE,'JOB_ACTIVE','任务已在后台执行')
                if row:
                    db.execute("UPDATE runtime_jobs SET status='queued',error=NULL,token=NULL,lease_until=NULL,updated=? WHERE run_id=?",(time.time(),run_id))
                else:
                    db.execute('INSERT INTO runtime_jobs(id,run_id,owner,status,updated,thread_id,policy) VALUES(?,?,?,?,?,?,?)',(str(uuid4()),run_id,owner,'queued',time.time(),str(uuid4()),CONTRACT['runtime_extension']['graph_policy']))
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
            row=db.execute("SELECT id,run_id,owner,thread_id FROM runtime_jobs WHERE status='queued' OR (status='running' AND lease_until<?) ORDER BY updated LIMIT 1",(now,)).fetchone()
            if not row:return None
            token=str(uuid4())
            db.execute("UPDATE runtime_jobs SET status='running',token=?,lease_until=?,updated=?,generation=generation+1 WHERE id=?",(token,now+lease,now,row[0]))
            return dict(zip(('id','run_id','owner','thread_id'),row))|{'token':token}

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

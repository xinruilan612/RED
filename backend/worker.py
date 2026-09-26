"""Independent durable worker. Run separately from the web process."""
import argparse
import signal
import threading
import time
from uuid import uuid4
from backend.contracts import DomainError, CONTRACT, require
from backend.jobs import Jobs, graph_policy
from backend.runtime import Runtime


class Worker:
    def __init__(self, service, lease=CONTRACT['runtime_extension']['lease_s'], fault=None):
        self.service,self.store,self.jobs=service,service.store,Jobs(service.store)
        self.lease,self.fault=lease,fault
        self.id=str(uuid4());self.stopped=threading.Event()

    def online(self):
        with self.store.connect() as db:
            db.execute('INSERT INTO runtime_workers VALUES(?,?) ON CONFLICT(id) DO UPDATE SET heartbeat=excluded.heartbeat',(self.id,time.time()))
            db.execute('DELETE FROM runtime_workers WHERE heartbeat<?',(time.time()-86400,))

    def once(self):
        self.online()
        job=self.jobs.claim(self.lease)
        if not job:return False
        done=threading.Event()
        def keep_alive():
            previous=time.monotonic()
            while not done.wait(self.lease/3):
                now=time.monotonic()
                try:
                    self.jobs.heartbeat(job,self.lease,now-previous);self.online()
                except Exception:
                    return  # Existing lease will expire; no unsafe local extension.
                previous=now
        heart=threading.Thread(target=keep_alive,daemon=True);heart.start()
        try:
            run=self.store.get(job['run_id'],job['owner'])
            require(job['policy']==graph_policy(run),'CONFIG_INVALID','任务执行策略不匹配，已停止')
            if run.workflow_type=='windtunnel':
                from backend.windtunnel_runtime import WindtunnelRuntime
                WindtunnelRuntime(self.service,self.jobs,job,self.fault).execute()
            else:
                Runtime(self.service,self.jobs,job,self.fault).execute()
            run=self.store.get(job['run_id'],job['owner'])
            self.jobs.finish(job,'waiting' if run.run_status=='WAITING_USER' else 'done')
        except Exception as error:
            run=self.store.get(job['run_id'],job['owner'])
            if run.run_status in ('SUCCEEDED','FAILED','CANCELLED','EXPIRED'):status='done'
            elif isinstance(error,DomainError) and error.code=='JOB_PAUSED':status='paused'
            else:status='blocked'
            message=str(error) if isinstance(error,DomainError) else '执行中断，检查点与已完成节点已保留；请核对后继续'
            self.jobs.finish(job,status,message)
        finally:
            done.set();heart.join(timeout=2)
        return True

    def run(self):
        while not self.stopped.is_set():
            try:worked=self.once()
            except Exception:
                worked=False  # DB outage: keep durable jobs; retry discovery, never a provider call.
            if not worked:self.stopped.wait(1)


def main():
    from backend.api import settings
    from backend.store import Store
    from backend.service import Service
    from backend.provider import load_config
    parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');args=parser.parse_args()
    env=settings();service=Service(Store(env.get('DATABASE_URL','runtime/web.sqlite')),load_config(),allow_windtunnel_live=env.get('WINDTUNNEL_ALLOW_LIVE','').lower()=='true')
    worker=Worker(service)
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:worker.stopped.set())
    if args.once:worker.once()
    else:worker.run()


if __name__=='__main__':main()

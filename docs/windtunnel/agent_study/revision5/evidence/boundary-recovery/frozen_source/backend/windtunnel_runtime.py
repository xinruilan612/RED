"""Durable content checks with stage-specific inputs and immutable node effects."""
import json
import time
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import StateGraph, START, END
from backend.contracts import DomainError, require
from backend.runtime import Runtime
from backend.workflow import digest
from backend.model_router import WINDTUNNEL_STAGES
from backend import windtunnel


class WindCursor(TypedDict, total=False):
    next: str
    node_key: str


AGENTS = {'wt_conditions':'audience', 'wt_read':'reviewer',
          'wt_verify':'research', 'wt_patch':'content'}


class WindtunnelRuntime(Runtime):
    def key(self, run, stage):
        messages, _ = windtunnel.messages_for(run,stage)
        return digest({'snapshot':run.snapshot_id,'batch':run.windtunnel.get('batch_id'),
                       'stage':stage,'messages':messages,'policy':run.context.get('model_policy')})

    def dispatch(self, state):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run=self.store._get(db,self.job['run_id'],self.job['owner'])
            if run.run_status in ('SUCCEEDED','FAILED','CANCELLED','EXPIRED'):return {'next':'end'}
            run=self.jobs.guard(db,self.job)
            if run.run_status=='WAITING_USER':return {'next':'human'}
            require(run.current_stage in WINDTUNNEL_STAGES,'INVALID_TRANSITION','风洞执行阶段无效')
            if run.run_status=='QUEUED':
                run.start();self.write(db,run)
            return {'next':run.current_stage,'node_key':self.key(run,run.current_stage)}

    def node(self, stage, state):
        key=state['node_key']
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run=self.jobs.guard(db,self.job)
            if db.execute('SELECT 1 FROM runtime_nodes WHERE run_id=? AND node_key=?',(run.run_id,key)).fetchone():return {}
            require(run.current_stage==stage and self.key(run,stage)==key,'VERSION_CONFLICT','风洞输入已变化')
            if not any(e['type']=='agent.started' and e['payload'].get('node_key')==key for e in run.events):
                run.event('agent.started',agent=AGENTS[stage],stage=stage,node_key=key,mode=run.context['mode'])
                self.write(db,run)
        self.fault('before_call',stage)
        messages,inputs=windtunnel.messages_for(run,stage)
        started=time.monotonic();call_id=None
        if run.context['mode']=='live':
            self.service.guard_windtunnel_live(run.context['model_policy'])
            value,tokens,call_id=self.service.executor.calls.invoke(
                run,AGENTS[stage],stage,messages,lambda db:self.jobs.guard(db,self.job),
                reuse=True,visible_sources=windtunnel.stage_sources(run,stage))
            self.fault('after_response',stage)
        else:
            value=windtunnel.simulate(run,stage);tokens=None
        try:
            output=windtunnel.normalize(run,stage,value)
        except DomainError as error:
            if call_id:self.service.executor.calls.validated(call_id,str(error))
            raise
        if call_id:self.service.executor.calls.validated(call_id,None)
        log={'id':str(uuid4()),'agent':AGENTS[stage],'stage':stage,'mode':run.context['mode'],
             'snapshot_id':run.snapshot_id,'input':inputs,'output':output,
             'duration_ms':round((time.monotonic()-started)*1000),
             'model_calls':1 if call_id else 0,'tokens':tokens,'cost':None,'call_id':call_id,
             'sources':windtunnel.stage_sources(run,stage)}
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current=self.jobs.guard(db,self.job,committing=True)
            if db.execute('SELECT 1 FROM runtime_nodes WHERE run_id=? AND node_key=?',(run.run_id,key)).fetchone():return {}
            require(current.current_stage==stage and self.key(current,stage)==key,'VERSION_CONFLICT','风洞输入已变化，结果未采用')
            windtunnel.apply_stage(current,stage,output)
            current.node_runs.append(log)
            current.event('agent.completed',agent=AGENTS[stage],stage=stage,node_ref=log['id'],mode=log['mode'])
            db.execute('INSERT INTO runtime_nodes VALUES(?,?,?,?,?,?)',
                       (run.run_id,key,stage,digest(inputs),json.dumps(log,ensure_ascii=False),time.time()))
            self.write(db,current)
        self.fault('after_commit',stage)
        return {}

    def graph(self, saver):
        graph=StateGraph(WindCursor)
        graph.add_node('dispatch',self.dispatch)
        graph.add_node('human',self.human)
        for stage in WINDTUNNEL_STAGES:
            graph.add_node(stage,lambda state,s=stage:self.node(s,state))
        graph.add_edge(START,'dispatch')
        graph.add_conditional_edges('dispatch',lambda state:END if state['next']=='end' else state['next'])
        for stage in (*WINDTUNNEL_STAGES,'human'):graph.add_edge(stage,'dispatch')
        return graph.compile(checkpointer=saver)

"""Four-role LangGraph with transactional domain effects and persistent checkpoints.

Graph state holds cursors, not authority. SQL owns users, leases, approvals,
inputs and immutable effects. Replaying a committed node never re-applies it.
"""
import copy
import json
import time
from contextlib import contextmanager
from dataclasses import asdict
from typing import TypedDict
from uuid import uuid4
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from backend.contracts import CONTRACT, DomainError, require
from backend.workflow import digest
from backend import demo, live
from backend.creator_context import enrich


class Cursor(TypedDict, total=False):
    snapshot: str
    iteration: int
    draft: str
    next: str


@contextmanager
def checkpointer(store):
    if store.postgres:
        from langgraph.checkpoint.postgres import PostgresSaver
        with PostgresSaver.from_conn_string(store.path) as saver:
            # Session lock covers the library's concurrent-index migrations.
            saver.conn.execute('SELECT pg_advisory_lock(748215902)')
            try: saver.setup()
            finally: saver.conn.execute('SELECT pg_advisory_unlock(748215902)')
            yield saver
    else:
        from langgraph.checkpoint.sqlite import SqliteSaver
        with SqliteSaver.from_conn_string(store.path+'.checkpoints') as saver:
            saver.setup()
            yield saver


class Runtime:
    def __init__(self, service, jobs, job, fault=None):
        self.service,self.store,self.jobs,self.job=service,service.store,jobs,job
        self.fault=fault or (lambda point,stage:None)

    def read(self):return self.store.get(self.job['run_id'],self.job['owner'])

    def write(self, db, run):
        run.status_version+=1
        db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(asdict(run),ensure_ascii=False),run.run_id))

    def dispatch(self, state):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run=self.read()  # No mutation from the graph cursor or browser data.
            if run.run_status in CONTRACT['terminal_states']:return {'next':'end'}
            run=self.jobs.guard(db,self.job)
            if run.run_status=='QUEUED':
                run.start();self.write(db,run)
            from backend.jobs import next_creation_stage
            nxt=next_creation_stage(run)
            execution=run.context.get('runtime_execution',{})
            if execution.get('mode')=='step' and nxt not in (execution.get('target'),'human'):
                nxt='end'
            return {'snapshot':run.snapshot_id,'iteration':run.iteration,'draft':run.drafts[-1]['ref'] if run.drafts else '', 'next':nxt}

    def human(self, state):
        # Human action is validated in Service/Run, never by the resume value.
        run=self.read()
        if run.run_status=='WAITING_USER':
            interrupt({'reason':run.wait_reason,'draft_ref':run.drafts[-1]['ref'] if run.drafts else None,'review_ref':run.review['ref'] if run.review else None})
        return {}

    def web_research(self, state):
        from backend.web_research import collect
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run=self.jobs.guard(db,self.job)
            web=run.context.get('web_research',{})
            if web.get('status')=='complete':return {}
            require(web.get('enabled') and run.context.get('mode')=='live','INVALID_INPUT','没有授权本次联网调查')
            require(web.get('status')=='pending','SOURCE_UNAVAILABLE','联网调查未完成或已中断。未重复搜索、未调用模型；请查看调查记录，调整搜索词后新建任务。')
            web['status']='searching'
            run.event('tool.started',tool='public_web_research',queries=web['queries'])
            self.write(db,run)
        def guard():
            with self.store.connect() as db:self.jobs.guard(db,self.job)
        report=collect(web['queries'],before_request=guard)
        self.fault('after_web_response','web_research')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current=self.jobs.guard(db,self.job,committing=True)
            require(current.snapshot_id==run.snapshot_id,'VERSION_CONFLICT','调查输入已变化')
            current.context['web_research']={**web,**report}
            current.context['evidence']=current.context.get('evidence',[])+report['sources']
            current.event('tool.completed' if report['status']=='complete' else 'tool.failed',tool='public_web_research',status=report['status'],source_count=len(report['sources']))
            self.write(db,current)
        require(report['status']=='complete','SOURCE_UNAVAILABLE','没有读到相关网页正文，已停止在模型调用前。请查看联网记录，调整搜索词后新建任务。')
        return {}

    def join(self, state):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run=self.jobs.guard(db,self.job)
            if run.current_stage=='brief' and run.run_status=='RUNNING':
                run.join(run.context['allow_hypothesis']);self.write(db,run)
        return {}

    def node(self, stage, state):
        agent=stage if stage in ('audience','research') else 'reviewer' if stage=='review' else 'content'
        # The key derives from the scheduling checkpoint, not the already-mutated Run.
        key=digest({'snapshot':state['snapshot'],'iteration':state['iteration'],'stage':stage,
                    'draft':state['draft'] if stage in ('review','revise') else ''})
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run=self.jobs.guard(db,self.job)
            if db.execute('SELECT 1 FROM runtime_nodes WHERE run_id=? AND node_key=?',(run.run_id,key)).fetchone():return {}
            require(run.snapshot_id==state['snapshot'],'VERSION_CONFLICT','输入快照已变化')
            if not any(e['type']=='agent.started' and e['payload'].get('node_key')==key for e in run.events):
                run.event('agent.started',agent=agent,stage=stage,node_key=key,mode=run.context.get('mode','simulation'))
                self.write(db,run)
        self.fault('before_call',stage)
        started=time.monotonic()
        if run.context.get('mode')=='live':
            messages,inputs=live.messages_for(run,stage)
            try:
                value,tokens,call_id=self.service.executor.calls.invoke(run,agent,stage,messages,lambda db:self.jobs.guard(db,self.job),reuse=True)
            except DomainError as error:
                if error.code!='STAGE_ATTEMPT_LIMIT' or stage not in ('review','revise') or not run.drafts:
                    raise
                with self.store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    current=self.jobs.guard(db,self.job,committing=True)
                    require(current.snapshot_id==run.snapshot_id and current.drafts[-1]['ref']==state['draft'],
                            'VERSION_CONFLICT','稿件已变化，不能结束旧阶段')
                    current._transition('WAITING_USER','revision_limit')
                    self.write(db,current)
                return {}
            self.fault('after_response',stage)
            try:output=enrich(stage,live.normalize(run,stage,value),run.context)
            except DomainError as error:
                self.service.executor.calls.validated(call_id,str(error));raise
            self.service.executor.calls.validated(call_id,None)
            log={'id':str(uuid4()),'agent':agent,'stage':stage,'mode':'live','snapshot_id':run.snapshot_id,
                 'input':inputs,'output':output,'duration_ms':round((time.monotonic()-started)*1000),
                 'model_calls':1,'tokens':tokens,'cost':None,'call_id':call_id,'tools':['knowledge_snapshot'] if run.context.get('evidence') else [],
                 'memory':'读取本任务的账号与证据快照'}
            from backend.citation_ids import repair
            _,repairs=repair(stage,value,live.material_records(run.context))
            if repairs:log['citation_repairs']=repairs
        else:
            # Template execution shares graph persistence without pretending to call a model.
            if stage in ('audience','research'):
                output=getattr(demo,stage)(run.context)
                log=demo.node(agent,stage,run.context,lambda:output)
            else:
                simulated=copy.deepcopy(run);demo.advance(simulated)
                log=simulated.node_runs[-1];output=log['output']
            log.update(id=str(uuid4()),snapshot_id=run.snapshot_id)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current=self.jobs.guard(db,self.job,committing=True)
            if db.execute('SELECT 1 FROM runtime_nodes WHERE run_id=? AND node_key=?',(run.run_id,key)).fetchone():return {}
            require(current.snapshot_id==run.snapshot_id,'VERSION_CONFLICT','节点输入已失效')
            expected='brief' if stage in ('audience','research') else 'reviewer' if stage=='review' else 'content'
            require(current.run_status=='RUNNING' and current.current_stage==expected,'VERSION_CONFLICT','节点已过期')
            if stage in ('review','revise'):
                require(current.drafts[-1]['ref']==state['draft'],'VERSION_CONFLICT','稿件已变化，拒绝旧结果')
            current.node_runs.append(log)
            current.event('agent.completed',agent=agent,stage=stage,mode=log['mode'],node_ref=log['id'])
            if stage in ('audience','research'):current.branch(stage,current.snapshot_id,'succeeded',output)
            elif stage=='review':
                gates=live.review_gates(current,output) if log['mode']=='live' else {k:True for k in CONTRACT['review_policy']['required_gates']}
                current.reviewed(output,gates,fail_on_limit=log['mode']=='live')
            else:
                if stage!='revise':
                    current.artifacts.append({'stage':stage,'value':output,'snapshot_id':current.snapshot_id})
                    current.event('artifact.created',stage=stage,mode=log['mode'])
                if stage in ('body','revise'):current.draft(output)
            db.execute('INSERT INTO runtime_nodes VALUES(?,?,?,?,?,?)',(run.run_id,key,stage,digest(log['input']),json.dumps(log,ensure_ascii=False),time.time()))
            self.write(db,current)
        self.fault('after_commit',stage)
        return {}

    def graph(self, saver):
        graph=StateGraph(Cursor)
        graph.add_node('dispatch',self.dispatch)
        graph.add_node('human',self.human)
        graph.add_node('join',self.join)
        graph.add_node('web_research',self.web_research)
        graph.add_edge('web_research','dispatch')
        for stage in ('audience','research','strategy','outline','hook','title','body','revise','review'):
            graph.add_node(stage,lambda state,s=stage:self.node(s,state))
        def route(state):
            return ['audience','research'] if state['next']=='brief' else END if state['next']=='end' else state['next']
        graph.add_edge(START,'dispatch')
        graph.add_conditional_edges('dispatch',route)
        graph.add_edge(['audience','research'],'join')
        for stage in ('join','human','strategy','outline','hook','title','body','revise','review'):graph.add_edge(stage,'dispatch')
        return graph.compile(checkpointer=saver)

    def execute(self):
        with checkpointer(self.store) as saver:
            graph=self.graph(saver)
            config={'configurable':{'thread_id':self.job['thread_id']},'recursion_limit':100}
            snapshot=graph.get_state(config)
            if snapshot.tasks and any(t.interrupts for t in snapshot.tasks):value=Command(resume='reload_validated_domain_state')
            elif snapshot.next:value=None
            else:value={}
            graph.invoke(value,config)

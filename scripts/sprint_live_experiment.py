"""Authorized controlled arm study; provenance explicit, no human quality claims.

Shares the ORIGINAL algorithms-live/budget.sqlite ledger, never resets it.
Unknown usage blocks subsequent calls. Model receipts stay under ignored runtime.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import time
import threading
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARMS = {
    'A': {'enabled': False},
    'B': {'enabled': True, 'coverage': True, 'structure': False, 'ask_questions': False},
    'C': {'enabled': True, 'coverage': False, 'structure': False, 'ask_questions': True},
    'D': {'enabled': True, 'coverage': False, 'structure': True, 'ask_questions': False},
    'E': {'enabled': True, 'coverage': True, 'structure': True, 'ask_questions': True},
}


# User explicitly raised the cumulative ceiling to CNY 10; historical ledger spending remains included.
class CumulativeCap:
    call_lock = threading.Lock()

    def __init__(self, adapter, ledger, cap_cny=10):
        if not 0 < cap_cny <= 10:
            raise ValueError('授权累计上限不可超过10元')
        self.adapter, self.ledger, self.limit = adapter, Path(ledger), int(cap_cny*1e6)
        # Require existing ledger; a missing ledger must not silently erase cost.
        if not self.ledger.is_file():
            raise ValueError('原累计账本不存在，拒绝重新从零计费')
        with self.connect() as db:
            self.validate_ledger(db)

    def connect(self):
        # mode=rw fails closed if the ledger disappears between checks/calls.
        return sqlite3.connect(self.ledger.resolve().as_uri()+'?mode=rw', uri=True)

    @staticmethod
    def validate_ledger(db):
        for reserved, billed, tokens, state in db.execute('SELECT reserved,billed,tokens,state FROM attempts'):
            if (type(reserved) is not int or reserved < 0
                    or (billed is not None and (type(billed) is not int or billed < 0))
                    or (tokens is not None and (type(tokens) is not int or tokens < 0))
                    or state not in ('calling','unknown','received','not_sent')
                    or (state == 'received' and (billed is None or tokens is None))):
                raise ValueError('累计账本存在无效记录，拒绝继续调用；请先人工核对')

    def spent(self):
        with self.connect() as db:
            self.validate_ledger(db)
            return db.execute('SELECT COALESCE(SUM(COALESCE(billed,reserved)),0) FROM attempts').fetchone()[0]

    def complete_result(self, messages, max_tokens=3000):
        # Audience/research run in parallel. Serialize only paid transport, so
        # one in-flight request cannot falsely block its companion branch.
        with self.call_lock:
            return self._complete_result(messages, max_tokens)

    def _complete_result(self, messages, max_tokens=3000):
        from backend.contracts import DomainError
        raw = json.dumps(messages, ensure_ascii=False).encode()
        bound = len(raw)+1024
        if bound > 100000 or type(max_tokens) is not int or not 0 < max_tokens <= 6000:
            raise DomainError('MODEL_REQUEST_NOT_SENT', '超出已核对价格与输出档位')
        identity, held = uuid4().hex, (bound+max_tokens)*8
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.validate_ledger(db)
            if db.execute("SELECT COUNT(*) FROM attempts WHERE state IN ('unknown','calling')").fetchone()[0]:
                raise DomainError('MODEL_REQUEST_NOT_SENT', '存在未知用量或在途调用，不再发送')
            used = db.execute('SELECT COALESCE(SUM(COALESCE(billed,reserved)),0) FROM attempts').fetchone()[0]
            if used+held > self.limit:
                raise DomainError('MODEL_REQUEST_NOT_SENT', '累计授权预留不足，未发送请求')
            db.execute('INSERT INTO attempts VALUES(?,?,NULL,NULL,?)', (identity, held, 'calling'))
        print('request', identity[:8], 'held_cny', held/1e6, flush=True)
        try:
            value, tokens, meta = self.adapter.complete_result(messages, max_tokens=max_tokens)
            if type(tokens) is not int or tokens < 0 or tokens*8 > held:
                raise DomainError('QA_BUDGET', '用量超过保守预留，停止后续请求')
            with self.connect() as db:
                db.execute('UPDATE attempts SET billed=?,tokens=?,state=? WHERE id=?',
                           (tokens*8, tokens, 'received', identity))
            print('received cumulative_upper_cny', self.spent()/1e6, flush=True)
            return value, tokens, meta
        except Exception as error:
            not_sent = isinstance(error, DomainError) and error.code == 'MODEL_REQUEST_NOT_SENT'
            with self.connect() as db:
                db.execute('UPDATE attempts SET billed=?,state=? WHERE id=?',
                           (0 if not_sent else None, 'not_sent' if not_sent else 'unknown', identity))
            raise


def study_inputs(dataset, answers):
    tasks = dataset.get('items', dataset.get('tasks', [])) if isinstance(dataset, dict) else dataset
    if not isinstance(tasks, list) or not tasks:
        raise ValueError('任务数据必须包含非空 items 数组')
    if isinstance(answers, dict) and isinstance(answers.get('items'), list):
        grouped = {}
        for item in answers['items']:
            answer = item.get('fixed_answer')
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError('标准补料答案不能为空')
            grouped.setdefault(item['task_id'], []).append(answer)
        answers = {key: '\n'.join(values) for key, values in grouped.items()}
    if not isinstance(answers, dict):
        raise ValueError('标准答案格式无效')
    return tasks, answers


def creation_input(task):
    """Projection excludes sealed answers, proposed gold labels and provenance."""
    original = task.get('input', task)
    return {key: original[key] for key in ('topic','audience','material','creation')}


def stop_before_new_case(spent_micro, authorized_cny, safety_margin_micro=200000):
    """A new case needs headroom; every actual call still uses a hard reservation."""
    if not 0 < authorized_cny <= 10:
        raise ValueError('授权累计上限不可超过10元')
    return spent_micro >= max(0, int(authorized_cny*1e6)-safety_margin_micro)


def experiment_metadata(dataset, tasks, task_ids, arms, dataset_hash, answers_hash,
                        authorized_cny, data_kind='fictional_controlled_task', comparison_scope=None):
    if data_kind not in ('fictional_controlled_task','public-source-constructed'):
        raise ValueError('实验数据类型无效')
    if len(set(arms))!=len(arms) or len(arms)<2 or not set(arms)<=set(ARMS):
        raise ValueError('实验至少需要两个不重复的合法组')
    if len(set(task_ids))!=len(task_ids):
        raise ValueError('任务ID不可重复')
    selected={task['id']:task for task in tasks if task['id'] in task_ids}
    if set(selected)!=set(task_ids):
        raise ValueError('所选任务不存在')
    note = ('官方公开资料构造任务，不是用户投稿或真实创作者试用。' if data_kind=='public-source-constructed'
            else '虚构受控任务，不是真实用户投稿。')
    return {'data_kind':data_kind,'is_user_submission':False,'has_human_quality_scores':False,
            'groups':list(arms),'task_ids':list(task_ids),'authorized_cumulative_cny':authorized_cny,
            'comparison_scope':comparison_scope or '相同初始资料、按固定标准答案补料的流程对照；额外信息属于干预一部分，不能估计纯算法文章质量因果贡献。',
            'evidence_scope':note+'未完成独立人工盲评，不能报告人工质量提升。',
            'provenance':{'dataset_sha256':dataset_hash,'fixed_answers_sha256':answers_hash,
                          'initial_input_sha256':{key:hashlib.sha256(json.dumps(creation_input(task),ensure_ascii=False,sort_keys=True).encode()).hexdigest() for key,task in selected.items()},
                          'sources':{key:task.get('sources') or {'source_id':task.get('source_id'),'source_urls':task.get('source_urls',[]),'original_data_kind':task.get('data_kind')} for key,task in selected.items()}}}


def public_summary(state, cumulative_upper_micro, stop_reason='completed_selected_cases'):
    public={k:state[k] for k in ('cases','source_model','initial_upper_micro','experiment') if k in state}
    public['scope']='同初始资料、按统一标准补料的五组流程探索；C/E额外信息属于干预一部分，不能估计纯算法文章质量因果贡献；虚构任务且无真人评价。'
    if state.get('experiment'):
        design=state['experiment']
        public['scope']=design['comparison_scope']+' '+design['evidence_scope']
    public['cumulative_upper_micro']=cumulative_upper_micro
    public['stop_reason']=stop_reason
    return public


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--authorized-cny', type=float, required=True)
    parser.add_argument('--study-id', default='batch1')
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--task-ids', nargs='+', required=True)
    parser.add_argument('--arms', nargs='+', choices=ARMS, default=list(ARMS))
    parser.add_argument('--answers', type=Path, required=True)
    parser.add_argument('--data-kind', choices=('fictional_controlled_task','public-source-constructed'),default='fictional_controlled_task')
    parser.add_argument('--comparison-scope', default=None)
    args = parser.parse_args()
    if not 0 < args.authorized_cny <= 10:
        parser.error('本轮授权累计10元，包含原账本所有历史消费')
    os.environ['YOUJI_EMBEDDING_MODEL_PATH'] = 'off'
    from fastapi.testclient import TestClient
    from backend.api import create_app
    from backend.provider import Config
    from backend.credentials import CredentialVault
    from backend.store import Store
    from backend.worker import Worker
    from scripts.build_original_creation_report import sanitize
    if not args.study_id.replace('-', '').isalnum():
        parser.error('study-id须为字母数字或连字符')
    base = ROOT/'runtime'/('sprint-live-'+args.study_id)
    base.mkdir(parents=True, exist_ok=True)
    ledger = ROOT/'runtime/algorithms-live/budget.sqlite'
    store = Store(str(base/'study.sqlite'))
    app = create_app(store, Config(), origin='http://testserver', invite='')
    service = app.state.service
    adapter = service.models.adapter
    service.models.adapter = lambda route, owner: CumulativeCap(adapter(route, owner), ledger, args.authorized_cny)
    path = base/'private-state.json'
    state = json.loads(path.read_text()) if path.exists() else {}
    def save():
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2)); path.chmod(0o600)
    def summarize(reason='completed_selected_cases'):
        (base/'summary.json').write_text(json.dumps(public_summary(state,CumulativeCap(None,ledger).spent(),reason),ensure_ascii=False,indent=2))
    dataset = json.loads(args.dataset.read_text())
    tasks, answers = study_inputs(dataset, json.loads(args.answers.read_text()))
    for selected in args.task_ids:
        if not any(t.get('id') == selected for t in tasks) or selected not in answers:
            raise ValueError('所选任务或对应标准补料答案不存在：'+selected)
    design=experiment_metadata(dataset,tasks,args.task_ids,args.arms,hashlib.sha256(args.dataset.read_bytes()).hexdigest(),hashlib.sha256(args.answers.read_bytes()).hexdigest(),args.authorized_cny,args.data_kind,args.comparison_scope)
    if state.get('experiment') and state['experiment']!=design:
        raise ValueError('本study-id已绑定不同实验输入/分组/授权，请保留旧结果并选新study-id')
    with TestClient(app) as client:
        csrf = client.get('/api/session').json()['csrf']
        def post(url, data):
            response = client.post(url, json=data, headers={'Origin':'http://testserver','X-CSRF-Token':csrf})
            if response.status_code >= 400:
                raise RuntimeError(url+' '+response.text[:400])
            return response.json()
        if not state:
            password = 'Qa-'+secrets.token_hex(7)
            csrf = post('/api/auth/register', {'username':'sprint_study', 'password':password})['csrf']
            account = client.get('/api/operations').json()['accounts'][0]['id']
            source = Store(str(ROOT.parent/'data/teacher.sqlite'))
            with source.connect() as db:
                rows = db.execute('SELECT payload,secret FROM model_connections WHERE active=1').fetchall()
            row = next(r for r in rows if json.loads(r[0]).get('model') == 'qwen-plus'
                       and json.loads(r[0]).get('provider') == 'qwen'
                       and json.loads(r[0]).get('base_url') == 'https://dashscope.aliyuncs.com/compatible-mode/v1')
            conf = json.loads(row[0])
            key = CredentialVault(source, environ={'PUBLIC_ORIGIN':'http://127.0.0.1'}).decrypt(row[1])
            conn = post('/api/models/connections', {k:conf[k] for k in ('provider','model','base_url','protocol','json_mode','rate_usd_per_million')}
                        | {'label':'冲刺隔离实验','api_key':key,'run_budget_usd':2,'day_budget_usd':3})
            del key, row, rows
            post('/api/models/default', {'connection_id':conn['id']})
            state.update(experiment=design, scope='同初始资料、按统一标准补料的五组流程探索；额外信息属于干预一部分，不能估计纯算法文章质量的因果贡献。', password=password, account_id=account, cases=[], source_model='qwen-plus', initial_upper_micro=CumulativeCap(None,ledger).spent())
            save()
        else:
            csrf = post('/api/auth/login', {'username':'sprint_study','password':state['password']})['csrf']
            if 'experiment' not in state:
                state['experiment']=design;save()
        for task_id in args.task_ids:
            source_task = next(t for t in tasks if t['id']==task_id)
            task = creation_input(source_task)
            reference = source_task.get('reference_example') or {}
            # Only fictional profiles are imported, with the same library for all arms.
            if task_id not in state.get('references', {}):
                from backend.creation_taxonomy import taxonomy
                original_text = reference.get('text') or task['topic']+'写法参考：选购前先问需求。参数来自本次资料。先核对尺寸，再看限制。注意适用条件。收藏核对清单。'
                # This authored fixture is imported with an explicit metadata
                # header, never passed off as an unmodified real article. BM25
                # must find actual terms, not a forced retrieval result.
                labels = ' '.join(taxonomy()['domains'][d]['label'] for d in task['creation']['domains'])
                prefix = '资料标签（非正文）：'+labels+' 图文笔记 开篇 结构 表达。以下是受控自编参考。\n\n'
                imported = prefix+original_text
                ref = post('/api/knowledge', dict(account_id=state['account_id'],title=reference.get('title') or '虚构选购结构参考-'+task_id,
                    text=imported,classification=dict(domains=task['creation']['domains'],channel='xiaohongshu',format='note',material_type='example')))
                state.setdefault('reference_imports', {})[task_id] = {'original_text_sha256':hashlib.sha256(original_text.encode()).hexdigest(),
                    'imported_text_sha256':hashlib.sha256(imported.encode()).hexdigest(), 'metadata_prefix':prefix,
                    'scope':'明确标签头加原始受控正文；不是未修改的真实参考文章'}
                state.setdefault('references',{})[task_id]=ref['id'];save()
            for arm in args.arms:
                case_id = task_id+'-'+arm
                old = next((c for c in state['cases'] if c['id']==case_id), None)
                if old:
                    continue  # Retain failures; no automatic retry or cherry-picking.
                if stop_before_new_case(CumulativeCap(None, ledger).spent(),args.authorized_cny):
                    print('budget_stop_before_new_case', flush=True);summarize('budget_stop_before_new_case');return
                run = post('/api/runs',dict(topic=task['topic'],audience=task['audience'],tone='清楚自然克制',material=task['material'],
                    mode='live',allow_hypothesis=False,web_research={'enabled':False,'queries':[]},creation=task['creation'],
                    operations={'account_id':state['account_id'],'platform':'xiaohongshu','account':'虚构实验'},
                    knowledge={'enabled':False,'automatic_references':True},algorithm_options=ARMS[arm]))
                item = {'id':case_id,'task_id':task_id,'arm':arm,'run_id':run['run_id'], 'options':ARMS[arm],
                        'input_sha256':hashlib.sha256(task['material'].encode()).hexdigest(),'started':time.time()}
                state['cases'].append(item);save()
                def get(): return client.get('/api/runs/'+item['run_id']).json()
                def start():
                    r=get();post('/api/runs/'+r['run_id']+'/background',{'action':'start','version':r['status_version'],'key':uuid4().hex})
                    Worker(service).once()
                start();run=get()
                if run['context'].get('algorithm_questions_status') == 'pending':
                    item['asked_questions']=run['context']['algorithm_state']['gap_ranking']['questions']
                    answer = answers[task_id]
                    if isinstance(answer,dict): answer=answer['material']
                    item['answer_sha256']=hashlib.sha256(answer.encode()).hexdigest()
                    post('/api/runs/'+item['run_id']+'/actions',{'action':'supplement','version':run['status_version'],'key':uuid4().hex,
                         'payload':{'material':answer,'allow_hypothesis':False}})
                    start();run=get()
                item.update(draft_available=bool(run.get('drafts')), completed=bool(run.get('drafts')) and run['run_status']=='WAITING_USER', run_status=run['run_status'],background=run['background']['status'],
                            elapsed_seconds=round(time.time()-item['started'],3),cumulative_upper_micro=CumulativeCap(None,ledger).spent(),
                            questions_status=run['context'].get('algorithm_questions_status'),review_decision=(run.get('review') or {}).get('decision'))
                (base/(case_id+'.json')).write_text(json.dumps(sanitize(run),ensure_ascii=False,indent=2));save()
                print('case',case_id,item['completed'],item['run_status'],item['background'],flush=True)
                if run['run_status'] not in ('CANCELLED','FAILED','SUCCEEDED','EXPIRED'):
                    post('/api/runs/'+item['run_id']+'/actions',{'action':'cancel','version':run['status_version'],'key':uuid4().hex,'payload':{}})
                with sqlite3.connect(ledger) as db:
                    if db.execute("SELECT COUNT(*) FROM attempts WHERE state IN ('unknown','calling')").fetchone()[0]:
                        print('unknown_usage_stop',flush=True);summarize('unknown_usage_stop');return
        summarize()


if __name__ == '__main__':
    main()

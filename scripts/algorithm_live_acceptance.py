"""Explicitly authorized acceptance on fictional material, isolated local data.

Run with --authorized-cny 5. Reuses one existing qwen-plus credential without
printing it, installs no new credentials in the production store. Never posts.
Persistent micro-CNY reservation ledger caps ALL attempts and unknown usage.
"""
import argparse
import json
import os
import secrets
from pathlib import Path
import sqlite3
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--authorized-cny', type=float, required=True)
    parser.add_argument('--restart-failed', action='store_true')
    args = parser.parse_args()
    if not 0 < args.authorized_cny <= 5:
        parser.error('本轮授权上限为人民币5元')
    os.environ['YOUJI_EMBEDDING_MODEL_PATH'] = 'off'
    from fastapi.testclient import TestClient
    from backend.api import create_app
    from backend.provider import Config
    from backend.credentials import CredentialVault
    from backend.store import Store
    from backend.worker import Worker
    from backend.contracts import DomainError
    base = ROOT/'runtime'/'algorithms-live'
    base.mkdir(parents=True, exist_ok=True)
    budget = base/'budget.sqlite'
    with sqlite3.connect(budget) as db:
        db.execute('CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, reserved INTEGER, billed INTEGER, tokens INTEGER, state TEXT)')
    def spent():
        with sqlite3.connect(budget) as db:
            return db.execute('SELECT COALESCE(SUM(COALESCE(billed,reserved)),0) FROM attempts').fetchone()[0]
    limit = int(args.authorized_cny * 1_000_000)
    class Capped:
        def __init__(self, adapter): self.adapter = adapter
        def complete_result(self, messages, max_tokens=3000):
            bound = sum(len(m['content'].encode('utf-8')) for m in messages)+1024
            if bound > 100000:
                raise DomainError('QA_BUDGET', '输入超出已核对价格档位')
            held = (bound+max_tokens)*8
            identity = uuid4().hex
            with sqlite3.connect(budget) as db:
                db.execute('BEGIN IMMEDIATE')
                used = db.execute('SELECT COALESCE(SUM(COALESCE(billed,reserved)),0) FROM attempts').fetchone()[0]
                if used+held > limit:
                    raise DomainError('QA_BUDGET', '累计费用预留超过本轮5元授权，未发请求')
                db.execute('INSERT INTO attempts VALUES(?,?,NULL,NULL,?)', (identity,held,'calling'))
            print('model_start', identity[:8], 'reserved_cny', held/1e6, flush=True)
            try:
                value,tokens,meta = self.adapter.complete_result(messages,max_tokens=max_tokens)
                with sqlite3.connect(budget) as db:
                    db.execute('UPDATE attempts SET billed=?,tokens=?,state=? WHERE id=?', (tokens*8,tokens,'received',identity))
                print('model_end', identity[:8], 'total_upper_cny', spent()/1e6, flush=True)
                return value,tokens,meta
            except Exception as error:
                unsent = isinstance(error,DomainError) and error.code == 'MODEL_REQUEST_NOT_SENT'
                with sqlite3.connect(budget) as db:
                    db.execute('UPDATE attempts SET billed=?,state=? WHERE id=?', (0 if unsent else None,'not_sent' if unsent else 'unknown',identity))
                raise
    store = Store(str(base/'acceptance.sqlite'))
    app = create_app(store,Config(),origin='http://testserver',invite='')
    service = app.state.service
    adapter = service.models.adapter
    service.models.adapter = lambda route, owner: Capped(adapter(route,owner))
    state_path = base/'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    qa_password = state.get('qa_password') or 'Qa-'+secrets.token_hex(7)
    def save():
        state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2))
        state_path.chmod(0o600)
    with TestClient(app) as client:
        csrf = client.get('/api/session').json()['csrf']
        def post(path, data):
            r = client.post(path,json=data,headers={'Origin':'http://testserver','X-CSRF-Token':csrf})
            if r.status_code >= 400:
                raise RuntimeError(path+' '+r.text[:500])
            return r.json()
        if not state:
            result = post('/api/auth/register',{'username':'algorithms_acceptance','password':qa_password})
            csrf = result['csrf']
            account = client.get('/api/operations').json()['accounts'][0]['id']
            source = Store(str(ROOT.parent/'data'/'teacher.sqlite'))
            with source.connect() as db:
                rows = db.execute('SELECT payload,secret FROM model_connections WHERE active=1').fetchall()
            row = next((r for r in rows if json.loads(r[0]).get('provider')=='qwen'
                        and json.loads(r[0]).get('model')=='qwen-plus'
                        and json.loads(r[0]).get('base_url')=='https://dashscope.aliyuncs.com/compatible-mode/v1'), None)
            if row is None:
                raise RuntimeError('没有可复用的已配置qwen-plus连接，尚未发送请求')
            conf = json.loads(row[0])
            key = CredentialVault(source,environ={'PUBLIC_ORIGIN':'http://127.0.0.1'}).decrypt(row[1])
            connection = post('/api/models/connections',{k:conf[k] for k in ('provider','model','base_url','protocol','json_mode','rate_usd_per_million')}
                              |{'label':'三算法隔离验收','api_key':key,'run_budget_usd':2,'day_budget_usd':3})
            del key,rows,row
            post('/api/models/default',{'connection_id':connection['id']})
            example = post('/api/knowledge',dict(account_id=account,title='虚构扫地机写法参考',
                text='买之前先问：家里能不能装？\n我亲测一个月才发现，示例机Z9容量999L并不适合所有人。\n先量安装位置，再核对上下水条件。\n注意柜门开启和管线位置。\n收藏清单，购买前逐项检查。',
                classification=dict(domains=['digital'],channel='xiaohongshu',format='note',material_type='example')))
            state.update(account_id=account, example_id=example['id'], cases=[],qa_password=qa_password)
            save()
        else:
            if not state.get('qa_password'):
                raise RuntimeError('旧QA状态缺少本地登录信息，停止且不发送模型请求')
            csrf = post('/api/auth/login',{'username':'algorithms_acceptance','password':qa_password})['csrf']
        if not state.get('matching_reference_id'):
            matched = post('/api/knowledge',dict(account_id=state['account_id'],title='数码图文笔记结构参考',
                text='数码图文笔记，开篇与结构表达参考。\n买之前先问：家里能不能装？\n我亲测一个月才发现，示例机Z9容量999L并不适合所有人。\n先量安装位置，再核对上下水条件。\n注意柜门开启和管线位置。\n收藏清单，购买前逐项检查。',
                classification=dict(domains=['digital'],channel='xiaohongshu',format='note',material_type='example')))
            state['matching_reference_id'] = matched['id']; save()
        material = ('以下仅为软件验收的虚构产品资料，不是真实商品参数。A1普通版水箱容量4L，机身高度35厘米。'
                    '安装说明：先测量柜体净高，柜体净高至少40厘米。不得堵住散热口。'
                    '没有亲测记录，请不要编造使用体验。上下水版的安装条件尚未提供。')
        if args.restart_failed:
            for prior in list(state['cases']):
                if prior.get('done'): continue
                old = client.get('/api/runs/'+prior['run_id']).json()
                if old['run_status'] not in ('CANCELLED','FAILED','SUCCEEDED','EXPIRED'):
                    post('/api/runs/'+prior['run_id']+'/actions',dict(action='cancel',version=old['status_version'],key=uuid4().hex,payload={}))
                state.setdefault('failed_attempts',[]).append(prior)
                (base/(prior['case']+'-failed-'+prior['run_id'][:8]+'.json')).write_text(json.dumps(old,ensure_ascii=False,indent=2))
                state['cases'].remove(prior)
            save()
        for case_id, ask in [('baseline', False), ('all_algorithms', True), ('structure_and_questions', True), ('final_validation', True), ('release_validation', True)]:
            item = next((x for x in state['cases'] if x['case'] == case_id), None)
            if item is None:
                run = post('/api/runs',dict(topic='虚构设备A1不同版本的安装条件对比' if case_id in ('structure_and_questions','final_validation','release_validation') else '虚构设备A1购买前的安装检查',audience='首次选购用户',tone='清楚克制',
                    material=material,mode='live',allow_hypothesis=True,web_research={'enabled':False,'queries':[]},
                    creation={'domains':['digital'],'channel':'xiaohongshu','format':'note','word_count':300},
                    operations={'account_id':state['account_id'],'platform':'xiaohongshu','account':'隔离验收'},
                    knowledge={'enabled':False,'automatic_references':True},
                    algorithm_options={'enabled':case_id!='baseline','ask_questions':ask}))
                item = {'case':case_id,'run_id':run['run_id'],'done':False}
                state['cases'].append(item);save()
            if item['done']: continue
            def getrun(): return client.get('/api/runs/'+item['run_id']).json()
            run = getrun()
            if run['run_status'] in ('QUEUED','RUNNING'):
                post('/api/runs/'+item['run_id']+'/background',{'action':'start','version':run['status_version'],'key':uuid4().hex})
                Worker(service).once()
            run = getrun()
            if run['context'].get('algorithm_questions_status')=='pending':
                item['questions'] = run['context']['algorithm_state']['gap_ranking']['questions']
                post('/api/runs/'+item['run_id']+'/actions',dict(action='skip_questions',version=run['status_version'],key=uuid4().hex,payload={}))
                run=getrun()
                post('/api/runs/'+item['run_id']+'/background',{'action':'start','version':run['status_version'],'key':uuid4().hex})
                Worker(service).once();run=getrun()
            item.update(done=bool(run.get('drafts')) and run['run_status']=='WAITING_USER',
                        status=run['run_status'],background=run['background'],upper_cny=spent()/1e6)
            (base/(case_id+'.json')).write_text(json.dumps(run,ensure_ascii=False,indent=2))
            save()
            print('case_result',case_id,item['status'],item['background']['status'], 'upper_cny',spent()/1e6,flush=True)
            if not item['done']:
                raise RuntimeError('验收未完成；保留调用与状态，不自动重试。')
            # Cancel only isolated QA task after saving receipt, freeing next task.
            post('/api/runs/'+item['run_id']+'/actions',dict(action='cancel',version=run['status_version'],key=uuid4().hex,payload={}))
        state['cost_upper_estimate_cny'] = spent()/1e6
        save()
        print('acceptance_complete',state['cost_upper_estimate_cny'],flush=True)


if __name__ == '__main__':
    main()

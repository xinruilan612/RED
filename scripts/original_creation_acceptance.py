"""Six controlled real-model cases through the production HTTP/Worker path.

Requires explicit operator budget authorization. No credentials are printed or
stored. Materials are authored fictional fixtures, not real product evidence.
"""
import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4
import requests

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from original_creation_cases import CASES,METHOD
from backend.api import settings
from backend.auth import Auth
from backend.store import Store
from backend.knowledge import Knowledge
from backend.accounts import PROFILE_FIELDS


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--schema',default='youji_connected_acceptance_20261010')
    parser.add_argument('--origin',default='http://127.0.0.1:8775')
    parser.add_argument('--execute-authorized',action='store_true')
    parser.add_argument('--resume-blocked',action='store_true')
    parser.add_argument('--retry-case',choices=[c['name'] for c in CASES])
    parser.add_argument('--refresh-prompt-case',choices=[c['name'] for c in CASES])
    parser.add_argument('--retry-authorized-unknown-case',choices=[c['name'] for c in CASES])
    parser.add_argument('--only-case',choices=[c['name'] for c in CASES])
    parser.add_argument('--defer-blocked-case',choices=[c['name'] for c in CASES])
    args=parser.parse_args()
    if not args.execute_authorized:parser.error('explicit --execute-authorized required for paid acceptance')
    if not args.schema.replace('_','').isalnum():parser.error('invalid schema')
    url=settings()['DATABASE_URL'];url+=('&' if '?' in url else '?')+urlencode({'options':'-csearch_path='+args.schema})
    store=Store(url)
    with store.connect() as db:
        row=db.execute('SELECT u.id,u.owner FROM users u JOIN xhs_sync_links x ON x.owner=u.owner LIMIT 1').fetchone()
    if not row:raise RuntimeError('No existing acceptance website account')
    auth=Auth(store);token=auth.issue(row[0]);session=requests.Session();session.trust_env=False
    session.cookies.set('youji_session',token)
    session.headers.update({'Origin':args.origin,'X-CSRF-Token':auth.session(token)['csrf']})
    def get(path):
        r=session.get(args.origin+path,timeout=90);r.raise_for_status();return r.json()
    def post(path,data):
        r=session.post(args.origin+path,json=data,timeout=180)
        if r.status_code>=400:raise RuntimeError(str(r.status_code)+' '+r.text[:600])
        return r.json()
    out=ROOT/'runtime/original_creation_acceptance';out.mkdir(parents=True,exist_ok=True)
    state=get('/api/operations');name='原创分类验收 · 虚构产品'
    account=next((a for a in state['accounts'] if a['name']==name),None)
    if account is None:
        state=post('/api/operations',{'action':'save_account','version':state['version'],'key':str(uuid4()),'payload':{
            'id':None,'name':name,'platform':'xiaohongshu','profile':{**{k:'' for k in PROFILE_FIELDS},'weekly_frequency':3}}})
        account=next(a for a in state['accounts'] if a['name']==name)
    account_id=account['id']
    # Existing real library is labelled with appended versions, preserving old snapshots.
    kb=Knowledge(store);backfills=[]
    for a in state['accounts']:
        backfills.extend(kb.backfill_classifications(row[1],a['id'])['document_ids'])
    existing={d['title']:d for d in get('/api/knowledge?account_id='+account_id)}
    def save(title,text,label):
        if title in existing:return existing[title]['id']
        doc=post('/api/knowledge',{'account_id':account_id,'title':title,'text':text,'classification':label})
        existing[title]=doc;return doc['id']
    save('验收自编通用原创方法',METHOD,{'domains':['general'],'channel':'any','format':'any','material_type':'method'})
    fact_ids={}
    for case in CASES:
        if case['facts']:
            fact_ids[case['product']]=save('虚构规格 · '+case['product'],case['facts'],{
                'domains':[case['domain']],'channel':'any','format':'any','material_type':'fact'})
        if case['sample']:
            save('自编结构样例 · '+case['name'],case['sample'],{
                'domains':[case['domain']],'channel':'xiaohongshu','format':case['format'],'material_type':'example'})
    report={'boundary':'自编受控虚构产品与样例；真实模型、真实本地向量、生产HTTP和Worker流程，不代表真实产品效果或全网原创查重',
            'budget_authorized_usd':.50,'account_id':account_id,'backfilled_documents':len(backfills),'cases':[]}
    report_path=out/'report.json'
    if report_path.exists():
        report=json.loads(report_path.read_text())
        if report.get('account_id')!=account_id:raise RuntimeError('Acceptance account changed; refusing to reuse report')
    if args.defer_blocked_case:
        blocked=next((c for c in report['cases'] if c['name']==args.defer_blocked_case),None)
        if not blocked:raise RuntimeError('No blocked case')
        held=get('/api/runs/'+blocked['run_id'])
        if held.get('background',{}).get('status')!='blocked':raise RuntimeError('Only blocked execution can be deferred')
        post('/api/runs/'+held['run_id']+'/actions',{'action':'cancel','version':held['status_version'],'key':str(uuid4()),'payload':{}})
        blocked['deferred_reason']='未知付费用量阻断；保留全部账本与快照，等待显式重试授权'
        blocked['closed_for_next_case']=True
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if args.retry_authorized_unknown_case:
        name=args.retry_authorized_unknown_case
        old=next((c for c in report['cases'] if c['name']==name),None)
        if not old or not old.get('deferred_reason'):raise RuntimeError('Only a preserved deferred failure can retry with explicit authorization')
        if any(c.get('explicit_unknown_retry') and c['name']==name for c in report.get('previous_attempts',[])):
            raise RuntimeError('One explicitly authorized retry already used')
        old['explicit_unknown_retry']='用户2026-10-11明确授权家具、园艺各重新运行一次，全部仍受US$0.50总上限约束'
        report.setdefault('previous_attempts',[]).append(old);report['cases'].remove(old)
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if args.retry_case:
        failed=next((c for c in report['cases'] if c['name']==args.retry_case),None)
        if not failed or failed.get('status')!='FAILED':raise RuntimeError('Only an inspected terminal failure can be retried')
        report.setdefault('previous_attempts',[]).append(failed)
        report['cases'].remove(failed)
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if args.refresh_prompt_case:
        from backend.contracts import CONTRACT
        old=next((c for c in report['cases'] if c['name']==args.refresh_prompt_case),None)
        if not old or not old.get('closed_for_next_case'):raise RuntimeError('Only completed inspected cases may refresh a changed prompt')
        old_run=get('/api/runs/'+old['run_id'])
        if old_run['context']['model_policy']['prompt_version']==CONTRACT['runtime_extension']['prompt_version']:
            raise RuntimeError('Prompt already current; refusing redundant paid validation')
        old['superseded_reason']='统一使用最终运行时提示词版本复验；原结果与费用保留'
        report.setdefault('previous_attempts',[]).append(old);report['cases'].remove(old)
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    for case in CASES:
        if args.only_case and case['name']!=args.only_case:continue
        entry=next((c for c in report['cases'] if c['name']==case['name']),None)
        if entry and entry.get('closed_for_next_case'):continue
        if entry:
            run=get('/api/runs/'+entry['run_id'])
        else:
            if report.get('conservative_cost_usd',0)>.48:
                raise RuntimeError('Remaining authorization cannot cover the next call reservation')
            run=post('/api/runs',{'mode':'live','topic':case['topic'],'audience':'需要了解产品规格的普通读者','tone':'清楚、自然、克制',
                'material':'这是受控虚构产品验收。请根据选定的本次产品规格写可阅读成稿，不能声称亲测或继承样例结论。',
                'allow_hypothesis':True,'operations':{'account_id':account_id,'platform':'xiaohongshu','account':name},
                'creation':{'domains':[case['domain']],'channel':'xiaohongshu','format':case['format'],'goal':'清楚介绍已有规格，帮助读者核对选择条件','word_count':180},
                'knowledge':{'enabled':True,'automatic_references':True,'document_ids':[fact_ids[case['product']]]},
                'web_research':{'enabled':False,'queries':[]}})
            entry={'name':case['name'],'run_id':run['run_id'],'status':'created'}
            report['cases'].append(entry);report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        routes=run['context']['model_policy']['routes']
        if any(float(r.get('run_budget_usd') or 1)>.10 for r in routes.values()):
            raise RuntimeError('Model route budget exceeds the authorized per-run reserve')
        # Per-call reservation also enforces the platform's cumulative daily cap.
        # Require every acceptance call to belong to that same day before relying on it.
        if any(r.get('billing_source')!='platform' or float(r.get('day_budget_usd') or 1)>.50 for r in routes.values()):
            raise RuntimeError('Authorized cumulative daily cap is not enforced')
        with store.connect() as db:
            ids=[c['run_id'] for c in report['cases']+report.get('previous_attempts',[])]
            old_calls=db.execute('SELECT COUNT(*) FROM live_calls WHERE run_id IN ('+','.join('?' for _ in ids)+') AND CAST(created AS date)<>CURRENT_DATE',ids).fetchone()[0]
        if old_calls:raise RuntimeError('Acceptance spans multiple days; cumulative authorization needs a new explicit guard')
        identity=run['run_id'];background=run.get('background',{}).get('status')
        if background=='blocked' and not args.resume_blocked:
            raise RuntimeError('Known blocked run requires inspected --resume-blocked; never silently resend')
        if background in ('idle','blocked'):
            post('/api/runs/'+identity+'/background',{'action':'start','version':run['status_version'],'key':str(uuid4())})
        print(json.dumps({'observing':case['name'],'run_id':identity},ensure_ascii=False),flush=True)
        deadline=time.monotonic()+420
        while time.monotonic()<deadline:
            run=get('/api/runs/'+identity)
            if run.get('background',{}).get('status') not in ('queued','running','pausing'):break
            time.sleep(2)
        (out/(identity+'.json')).write_text(json.dumps(run,ensure_ascii=False,indent=2))
        entry.update({'status':run.get('run_status'),'wait_reason':run.get('wait_reason'),
               'classification':run['context']['creation_classification'],'retrieval':run['context']['creation_retrieval'],
               'drafts':run.get('drafts',[]),'review':run.get('review'),'calls':run.get('calls',[]),'background':run.get('background')})
        with store.connect() as db:
            ids=[c['run_id'] for c in report['cases']+report.get('previous_attempts',[])]
            cost=db.execute('SELECT COALESCE(SUM(COALESCE(c.actual,c.reserved)*a.rate),0) FROM live_calls c JOIN model_audit a ON a.call_id=c.id WHERE c.run_id IN ('+','.join('?' for _ in ids)+')',ids).fetchone()[0]
            labelled=db.execute('SELECT v.metadata FROM knowledge_documents d JOIN knowledge_versions v ON v.document_id=d.id AND v.version=d.version WHERE d.owner=?',(row[1],)).fetchall()
        report['backfilled_documents']=sum(bool(json.loads(v[0]).get('classification_backfill')) for v in labelled)
        report['conservative_cost_usd']=float(cost);report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps({'finished':case['name'],'status':entry['status'],'wait_reason':entry['wait_reason'],'drafts':len(entry['drafts']),'cost':float(cost)},ensure_ascii=False),flush=True)
        if run.get('background',{}).get('status')=='blocked' or not entry['drafts']:
            raise RuntimeError('Acceptance blocked; preserve raw response and inspect before continuing')
        if run['run_status']=='WAITING_USER':
            # Free the one-active-task slot without pretending the human approved.
            post('/api/runs/'+identity+'/actions',{'action':'cancel','version':run['status_version'],'key':str(uuid4()),'payload':{}})
            entry['closed_for_next_case']=True
            entry['closure_note']='受控验收已保留成稿和审核；取消执行以释放单任务槽，未替用户确认或发布'
            report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        else:raise RuntimeError('Run has not reached human review; no next case issued')
    auth.logout(token)


if __name__=='__main__':main()

import sys,json,sqlite3,shutil,time,hashlib
from pathlib import Path
ROOT=Path('/Users/lanxinrui/Desktop/多agent协作社媒博主创建爆款推文');sys.path.insert(0,str(ROOT))
from scripts.run_windtunnel_agent_study import StudyRunner,write_json,sha
from backend import windtunnel as wt
src=ROOT/'runtime/windtunnel-agent-study-20261007/revision5/controls'
dst=ROOT/'runtime/windtunnel-agent-study-20261007/revision5/boundary-recovery'
assert not dst.exists(),'Never repeat recovery'
dst.mkdir()
with sqlite3.connect(src/'study.sqlite') as original,sqlite3.connect(dst/'study.sqlite') as target:original.backup(target)
shutil.copytree(src/'cases',dst/'cases')
r=StudyRunner(dst,budget_ledger=ROOT/'runtime/windtunnel-agent-study-20261007/budget.sqlite',continue_after_unknown=True,revision='v5.boundary-recovery')
r.freeze()
p=dst/'cases/S07/windtunnel';before=json.loads((p/'result.json').read_text());calls_before=r.client.summary()['calls'];owner='agent-study-S07-windtunnel';rid=before['run_id']
run=r.work(owner,rid)
assert run.wait_reason=='wt_patch'
assert r.client.summary()['calls']==calls_before,'Cached patch must not be resent'
patch=run.windtunnel['patches'][-1];cs=wt.conditions(run)
r.action(owner,rid,'apply_patch',dict(patch_id=patch['id'],item_ids=[i['id'] for i in patch['items']],base_hash=wt.draft(run)['hash']))
r.action(owner,rid,'recheck',dict(condition_set_id=cs['id']))
run=r.work(owner,rid);final=wt.draft(run)['text'];report=wt.current_report(run)
r.action(owner,rid,'finish')
result={**before,'revision':'v5.boundary-recovery','outcome':'completed','error':None,'previous_failure':before['error'],'recovery_kind':'known paid raw response revalidated without resending; two new recheck requests','source_failed_result_sha256':sha((src/'cases/S07/windtunnel/result.json').read_bytes()),'patch_count':len(patch['items']),'final_report':report,'unresolved_conditions':[x['condition_id'] for x in report['results'] if x['status']!='pass'],'final_sha256':sha(final),'changed':sha(final)!=before['original_sha256'],'calls':r.records(rid),'budget':r.client.summary()}
result['effective_repair_confirmed']=bool(result['patch_count'] and not result['unresolved_conditions'] and not report['new_issues'])
result.pop('fallback',None)
write_json(p/'result.json',result);(p/'final.txt').write_text(final);(p/'report.md').write_text(r.service.export(owner,rid))
write_json(dst/'recovery-audit.json',dict(source_case_sha256=result['source_failed_result_sha256'],source_run_id=rid,known_patch_reused_without_new_request=True,patch_calls_in_original=sum(x['stage']=='wt_patch' for x in before['calls']),patch_calls_after=sum(x['stage']=='wt_patch' for x in result['calls']),new_recheck_requests=r.client.summary()['calls']-calls_before,unchanged_cases=['S06','S10'],model_router_sha256=sha((ROOT/'backend/model_router.py').read_bytes()),recovery_script_sha256=sha(Path(__file__).read_bytes())))
print(json.dumps(dict(outcome=result['outcome'],effective_repair_confirmed=result['effective_repair_confirmed'],patch_count=result['patch_count'],budget=r.client.summary()),ensure_ascii=False))

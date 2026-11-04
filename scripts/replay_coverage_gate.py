"""Replay frozen, redacted planning inputs locally; never regenerate the draft.

This is a regression trace from an exploratory pilot, not a held-out quality test.
"""
import argparse
import copy
import hashlib
import json
from dataclasses import fields
from pathlib import Path
import sys

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from backend.workflow import Run
from backend.creation_algorithms import build, VERSION


def replay(snapshot):
    before=copy.deepcopy(snapshot)
    allowed={field.name for field in fields(Run)}
    run=Run(owner_id='redacted-replay',**{k:copy.deepcopy(v) for k,v in snapshot.items() if k in allowed and k!='owner_id'})
    old=run.context.get('algorithm_state',{}).get('planning',{})
    new=build(run)['planning']
    assert snapshot==before
    return {'schema':'youji-coverage-regression/1','planner_version':VERSION,
        'scope':'固定原模型候选的离线回放；只修正计划误计，不重写原稿，不构成修后真实文章质量验证。',
        'old':{k:old.get(k) for k in ('covered_weight','total_weight','weighted_coverage','selected_module_ids','covered_requirement_ids')},
        'new':{k:new.get(k) for k in ('covered_weight','total_weight','weighted_coverage','selected_module_ids','covered_requirement_ids')},
        'requirements':new['requirements'],'rejected_candidates':new['rejected_candidates'],
        'new_selected_modules':new['selected_modules'], 'original_snapshot_unchanged':True}


def main():
    p=argparse.ArgumentParser();p.add_argument('--receipts',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();rows=[]
    for source in sorted(args.receipts.glob('*-E.json')):
        raw=source.read_bytes();snapshot=json.loads(raw)
        result=replay(snapshot)
        rows.append({'case_id':source.stem,'receipt_sha256':hashlib.sha256(raw).hexdigest(),**result})
    if not rows:raise ValueError('No completed E receipts')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'cases':rows,'model_calls':0,'drafts_regenerated':0},ensure_ascii=False,indent=2))
    print(json.dumps([{'case_id':r['case_id'],'old':r['old'],'new':r['new']} for r in rows],ensure_ascii=False,indent=2))


if __name__=='__main__':main()

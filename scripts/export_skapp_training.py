"""Export account-owned fixed-window SKAPP inputs; local maintenance command."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.api import settings
from backend.store import Store
from backend.operations import Operations
from backend.topics import Topics


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner',required=True)
    parser.add_argument('--account',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    target=Path(args.output)
    if target.exists():
        parser.error('Output already exists; choose a new file')
    ops=Operations(Store(settings()['DATABASE_URL']))
    state=ops.read(args.owner)
    result=Topics(ops).training_data(args.owner,dict(account_id=args.account,version=state['version']))
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x',encoding='utf-8') as handle:
        json.dump(result,handle,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps({'eligible':len(result['records']),'excluded':len(result['excluded']),'minimum_training_records':result['minimum_training_records']},ensure_ascii=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())

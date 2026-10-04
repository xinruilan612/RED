"""Generate an audited one-call baseline; explicit opt-in, no automatic retry."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.api import settings
from backend.provider import load_config
from backend.store import Store
from backend.service import Service
from backend.comparison_baseline import generate

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--owner',required=True);p.add_argument('--run',required=True);p.add_argument('--output',required=True);p.add_argument('--acknowledge-live',action='store_true');a=p.parse_args()
    service=Service(Store(settings()['DATABASE_URL']),load_config())
    result=generate(service,a.owner,a.run,a.acknowledge_live)
    target=Path(a.output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('Saved comparison:',target,'; calls:',result['execution']['model_calls'],'tokens:',result['execution']['tokens'])

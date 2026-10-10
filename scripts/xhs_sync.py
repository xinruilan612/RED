"""Local administrator binding and bounded sync worker. No credentials in output."""
import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlencode
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.api import settings
from backend.store import Store
from backend.migrations import upgrade
from backend.operations import Operations
from backend.xhs_sync import XHSSync

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['bind','status','once','worker','bridge','serve'])
    parser.add_argument('--username');parser.add_argument('--account-id');parser.add_argument('--schema')
    parser.add_argument('--port',type=int,default=18061);args=parser.parse_args()
    if args.action=='bridge':
        root=Path(__file__).resolve().parents[1];folder=root/'runtime/xhs-local'
        os.umask(0o077)
        os.environ['AUTH_TOKEN']=(folder/'control-token').read_text().strip()
        os.environ['COOKIES_PATH']=str(folder/'session/cookies.json')
        os.chdir(folder)
        os.execv(str(folder/'bin/xiaohongshu-mcp'),['xiaohongshu-mcp','-port','127.0.0.1:'+str(args.port),'-headless=true'])
    target=settings().get('DATABASE_URL','runtime/web.sqlite')
    if args.schema:
        if not args.schema.replace('_','').isalnum() or not target.startswith(('postgresql://','postgres://')):parser.error('invalid PostgreSQL schema')
        target+=('&' if '?' in target else '?')+urlencode({'options':'-csearch_path='+args.schema})
    if args.action=='serve':
        os.environ['DATABASE_URL']=target;os.environ['PUBLIC_ORIGIN']='http://127.0.0.1:8775'
        os.execv(sys.executable,[sys.executable,'-m','backend.api','--port','8775'])
    store=Store(target);upgrade(store);sync=XHSSync(store)
    if args.action=='worker':
        from backend.worker import Worker
        from backend.service import Service
        from backend.provider import load_config
        Worker(Service(store,load_config())).run()
        return
    if args.action=='once':print({'claimed':sync.once()});return
    if not args.username:parser.error('--username required')
    with store.connect() as db:row=db.execute('SELECT owner FROM users WHERE username=?',(args.username.lower(),)).fetchone()
    if not row:parser.error('website user not found')
    accounts=[a for a in Operations(store).read(row[0])['accounts'] if a['platform']=='xiaohongshu' and (not args.account_id or a['id']==args.account_id)]
    if len(accounts)!=1:parser.error('specify one valid --account-id')
    result=sync.bind(row[0],accounts[0]['id'],args.port) if args.action=='bind' else sync.public(row[0],accounts[0]['id'])
    print({k:result.get(k) for k in ('bound','status','enabled','counts','last_at','next_at','error')})
if __name__=='__main__':main()

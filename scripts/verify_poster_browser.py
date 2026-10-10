"""Local poster browser acceptance against an isolated PostgreSQL schema.

Uses a constructed, already-confirmed manuscript, real rendering and downloads.
No model or third-party service is called.
No accounts, credentials, or manuscript data from the user's database are read.
"""
import argparse
import base64
from dataclasses import asdict
from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from uuid import uuid4
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='runtime/poster-local-evidence')
    args = parser.parse_args()
    import httpx
    import psycopg
    from playwright.sync_api import sync_playwright
    from backend.api import settings
    from backend.auth import Auth
    from backend.store import Store
    from backend.workflow import Run, digest
    base = settings()['DATABASE_URL']
    schema = 'youji_studio_browser_' + uuid4().hex
    output = (ROOT / args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    target = base + ('&' if '?' in base else '?') + 'options=-csearch_path%3D' + schema
    env = {**os.environ, 'DATABASE_URL': target, 'PUBLIC_ORIGIN': origin,
           'DEEPSEEK_API_KEY': '', 'REGISTRATION_INVITE': '', 'PYTHONDONTWRITEBYTECODE': '1'}
    process = None
    report = {'fixture': 'constructed manuscript, isolated PostgreSQL schema', 'checks': [], 'live_vision': []}
    with psycopg.connect(base, autocommit=True) as db:
        db.execute('CREATE SCHEMA ' + schema)
    try:
        with (output / 'server.log').open('w') as log:
            process = subprocess.Popen([sys.executable, '-m', 'backend.api', '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            with httpx.Client(base_url=origin, timeout=180, trust_env=False) as client:
                for _ in range(100):
                    try:
                        if client.get('/health').status_code == 200: break
                    except httpx.HTTPError: pass
                    time.sleep(.2)
                else: raise RuntimeError('Acceptance server did not start; inspect local server.log')
                csrf = client.get('/api/session').json()['csrf']
                def post(path, data):
                    return client.post(path, json=data, headers={'Origin': origin, 'X-CSRF-Token': csrf})
                response = post('/api/auth/register', {'username': 'studio_acceptance', 'password': 'Aa-' + secrets.token_hex(6)})
                assert response.status_code == 200, 'Fixture registration failed'
                csrf = response.json()['csrf']
                store = Store(target)
                owner = Auth(store).session(client.cookies.get('youji_session'))['owner']
                run = Run(owner, 'studio-acceptance-snapshot', context={'mode': 'simulation', 'topic': '罗技 M185 选购核对', 'audience': '大学生', 'tone': '清晰', 'material': '构造验收样本，不是真实测评或亲历记录。'})
                content = {'selected_title': '罗技 M185 选购前\n先核对这三件事', 'body': '① 接口\n先核对笔记本接口与接收器是否匹配。\n\n② 携带\n查看尺寸，结合自己的收纳空间选择。\n\n③ 供电\n购买前核对包装说明中的供电方式。', 'cta': '以产品包装及官方说明为准。', 'tags': ['选购核对']}
                run.drafts = [{'ref': 'draft@1', 'content': content, 'content_hash': digest(content), 'snapshot_id': run.snapshot_id}]
                run.accepted_ref = 'draft@1'
                run.acceptance = {'draft_ref': 'draft@1', 'content_hash': digest(content), 'snapshot_id': run.snapshot_id, 'mode': 'manual_override'}
                run.run_status = 'SUCCEEDED'
                with store.connect() as db:
                    db.execute('INSERT INTO runs(id,owner,payload) VALUES(?,?,?)', (run.run_id, owner, json.dumps(asdict(run), ensure_ascii=False)))
                route = '/api/runs/' + run.run_id + '/studio'
                data = {'draft_ref': run.accepted_ref, 'content_hash': digest(content)}
                def command(state, action, **kw):
                    res = post(route, {**data, 'action': action, 'idempotency_key': uuid4().hex,
                                     **({'expected_revision': state['revision']} if state else {}), **kw})
                    assert res.status_code == 200, f'{action} failed: {res.text[:500]}'
                    return res.json()
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(channel='chrome',headless=True)
                    context=browser.new_context(viewport={'width':1512,'height':1100},accept_downloads=True)
                    context.add_cookies([{'name':'youji_session','value':client.cookies.get('youji_session'),'url':origin}])
                    page=context.new_page(); errors=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto(origin,wait_until='networkidle')
                    page.locator(f'[data-run="{run.run_id}"]').click()
                    root=page.locator('[data-poster="root"]'); root.wait_for(timeout=45000)
                    root.locator('[data-poster="generate"]:enabled').wait_for(timeout=45000)
                    root.locator('[data-poster="source"]').set_input_files(str(ROOT/'frontend/assets/products/logitech-m185.jpg'))
                    root.locator('[data-poster="generate"]').click()
                    root.locator('[data-poster="preview"]:visible').wait_for(timeout=45000)
                    poster_route='/api/runs/'+run.run_id+'/poster'
                    first=client.get(poster_route).json()['state']['current']['data_url']
                    root.locator('select').select_option('minimal')
                    root.locator('[data-poster="generate"]:enabled').click()
                    root.locator('[data-poster="accept"]:enabled').wait_for(timeout=45000)
                    page.locator('[data-poster="root"][aria-busy="false"]').wait_for(timeout=45000)
                    second=client.get(poster_route).json()['state']['current']['data_url']; assert first!=second
                    root.locator('[data-poster="undo"]').click()
                    page.locator('[data-poster="root"][aria-busy="false"]').wait_for(timeout=45000)
                    assert client.get(poster_route).json()['state']['current']['data_url']==first
                    root.locator('[data-poster="redo"]').click()
                    page.locator('[data-poster="root"][aria-busy="false"]').wait_for(timeout=45000)
                    assert client.get(poster_route).json()['state']['current']['data_url']==second
                    root.locator('[data-poster="accept"]').click()
                    root.locator('[data-poster="download"]:enabled').wait_for(timeout=45000)
                    with page.expect_download() as pending:root.locator('[data-poster="download"]').click()
                    downloaded=output/'accepted.png';pending.value.save_as(str(downloaded))
                    assert downloaded.read_bytes()==base64.b64decode(second.split(',')[1])
                    assert store.get(run.run_id,owner).drafts[0]['content']==content
                    page.screenshot(path=str(output/'desktop.png'),full_page=True)
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'mobile overflow'
                    page.screenshot(path=str(output/'mobile.png'),full_page=True)
                    assert not errors, errors
                    report['checks']=['actual local photo rendering in two styles','confirmed copy unchanged','undo redo restores exact pixels','accepted download equals rendered bytes','390px no overflow','no browser errors']
                    browser.close()
                (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
                print(json.dumps(report,ensure_ascii=False))
    finally:
        if process:process.terminate();process.wait(timeout=15)
        with psycopg.connect(base,autocommit=True) as db:db.execute('DROP SCHEMA '+schema+' CASCADE')

if __name__=='__main__':main()

"""Actual browser acceptance against an isolated PostgreSQL schema.

Uses a constructed, already-confirmed manuscript, real rendering and downloads.
--live-vision additionally calls the local Ollama model (never a paid provider).
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
    parser.add_argument('--live-vision', action='store_true')
    parser.add_argument('--output', default='runtime/studio-evidence')
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
                initial = command(None, 'init', template='xhs-a', options={'studio': {'pages': {'0': {'layout': 'hero'}}}})
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(channel='chrome', headless=True)
                    context = browser.new_context(viewport={'width': 1512, 'height': 1100}, accept_downloads=True)
                    context.add_cookies([{'name': 'youji_session', 'value': client.cookies.get('youji_session'), 'url': origin}])
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(origin, wait_until='networkidle')
                    page.locator(f'[data-run="{run.run_id}"]').click()
                    studio = page.locator('[data-studio="root"]')
                    studio.wait_for(timeout=45000)
                    page.get_by_role('button', name='采用当前版本', exact=True).wait_for()
                    # Inspectable deterministic controls exercise the actual server and canvas.
                    report['checks'].append('authenticated confirmed manuscript opens studio')
                    page.locator('[data-studio="root"][aria-busy="false"]').wait_for(timeout=45000)
                    page.locator('[data-studio-element="image"]').click()
                    scale = page.locator('[data-studio="scale"]')
                    for _ in range(2):
                        with page.expect_response(lambda response: response.url.endswith(route) and response.request.method == 'POST', timeout=45000) as pending:
                            scale.press('ArrowLeft')
                        assert pending.value.status == 200
                        page.locator('[data-studio="root"][aria-busy="false"]').wait_for(timeout=45000)
                    initial = client.get(route).json()
                    assert initial['state']['current']['options']['studio']['pages']['0']['image']['scale'] == .9
                    report['checks'].append('real canvas selection and consecutive slider edits')
                    reference_file = output / 'reference.png'
                    reference_file.write_bytes(base64.b64decode(initial['preview']['pages'][0]['data_url'].split(',')[1]))
                    with page.expect_response(lambda response: response.url.endswith(route) and response.request.method == 'POST', timeout=45000) as pending:
                        page.locator('[data-studio-upload="reference"]').set_input_files(str(reference_file))
                    assert pending.value.status == 200
                    page.locator('[data-studio="root"][aria-busy="false"]').wait_for(timeout=45000)
                    initial = client.get(route).json()
                    assert initial['state']['assets'][0]['role'] == 'reference'
                    report['checks'].append('reference image uploads and persists')
                    page.screenshot(path=str(output / 'desktop.png'), full_page=True)
                    if args.live_vision:
                        current = client.get(route).json()
                        for feedback in ('把产品图缩小到0.9倍，背景改为浅绿色 #e7f0e7，保留所有文字。', '产品图再小一点，保持刚才的背景和其他元素不变。'):
                            start = time.monotonic()
                            result = command(current['state'], 'edit', feedback=feedback, page_index=0, element_id='image', reference_asset_id=initial['state']['assets'][0]['id'])
                            assert result['state']['has_pending'], 'Vision did not produce a candidate'
                            message = result['state']['messages'][-1]
                            report['live_vision'].append({'feedback': feedback, 'reply': message.get('text'), 'observation': message.get('observation'), 'duration_seconds': round(time.monotonic()-start, 2), 'design': result['state']['current']})
                            current = result
                            (output / 'live-progress.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
                        assert current['state']['current']['options']['studio']['pages']['0']['image']['scale'] < .9
                        report['checks'].append('real local vision compound edit and contextual follow-up')
                        feedback = '可以把这个产品图作为背景图吗？文字部分半透明化'
                        result = command(current['state'], 'edit', feedback=feedback, page_index=1, element_id='image')
                        parameters = result['state']['current']['options']['studio']['pages']['1']
                        assert parameters['image']['placement'] == 'background', 'Product did not become background'
                        assert 0 < parameters['body']['opacity'] < 1, 'Body did not become transparent'
                        message = result['state']['messages'][-1]
                        assert not message.get('observation'), 'Unverified model observation leaked'
                        report['live_vision'].append({'feedback': feedback, 'reply': message['text'], 'design': result['state']['current']})
                        current = result
                        (output / 'live-progress.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
                        report['checks'].append('reported background and text transparency request executes real operations')
                    else:
                        current = command(initial['state'], 'edit', operations=[{'page_index': 0, 'element_id': 'image', 'changes': {'scale': .85}}, {'page_index': 0, 'element_id': 'background', 'changes': {'color': '#e7f0e7'}}])
                    candidate_hash = current['preview']['design_hash']
                    reloaded = client.get(route).json()
                    assert reloaded['preview']['design_hash'] == candidate_hash
                    report['checks'].append('refresh restores pending candidate')
                    current = command(current['state'], 'undo')
                    current = command(current['state'], 'redo')
                    assert current['preview']['design_hash'] == candidate_hash
                    report['checks'].append('undo and redo recover exact design')
                    page.reload(wait_until='networkidle')
                    page.locator(f'[data-run="{run.run_id}"]').click()
                    page.locator('[data-studio="root"][aria-busy="false"]').wait_for(timeout=45000)
                    page.locator('[data-studio="compare"]').click()
                    assert page.locator('.studio-comparison').is_visible()
                    with page.expect_response(lambda response: response.url.endswith(route) and response.request.method == 'POST', timeout=45000) as accepted_response:
                        page.locator('[data-studio="accept"]').click()
                    assert accepted_response.value.status == 200
                    current = accepted_response.value.json()
                    page.locator('[data-studio="root"][aria-busy="false"]').wait_for(timeout=45000)
                    report['checks'].append('actual comparison and adoption buttons')
                    with page.expect_download(timeout=120000) as download_info:
                        page.locator('[data-studio="export"]').click()
                    download_info.value.save_as(str(output / 'downloaded-complete.zip'))
                    with zipfile.ZipFile(output / 'downloaded-complete.zip') as complete:
                        assert any(name.endswith('.png') for name in complete.namelist())
                        assert 'caption.txt' in complete.namelist()
                    report['checks'].append('browser downloads complete ZIP successfully')
                    exported = post(route + '/export', {**data, 'kind': 'images', 'expected_revision': current['state']['revision']})
                    assert exported.status_code == 200, exported.text[:200]
                    with zipfile.ZipFile(BytesIO(exported.content)) as archive:
                        manifest = json.loads(archive.read('manifest.json'))
                        assert manifest['design_hash'] == candidate_hash
                        png = next(name for name in archive.namelist() if name.endswith('01.png'))
                        assert archive.read(png) == base64.b64decode(current['preview']['pages'][0]['data_url'].split(',')[1])
                    (output / 'accepted-images.zip').write_bytes(exported.content)
                    report['checks'].append('accepted export is byte-identical to preview')
                    page.reload(wait_until='networkidle')
                    page.locator(f'[data-run="{run.run_id}"]').click()
                    studio.wait_for(timeout=45000)
                    studio.screenshot(path=str(output / 'studio.png'))
                    page.set_viewport_size({'width': 390, 'height': 844})
                    studio.screenshot(path=str(output / 'mobile.png'))
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Mobile viewport overflow'
                    assert not errors, errors
                    report['checks'].append('desktop and narrow layout, no browser exceptions')
                    context.close()
                    browser.close()
                report['status'] = 'passed'
                (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
                print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        if process:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        with psycopg.connect(base, autocommit=True) as db:
            db.execute('DROP SCHEMA ' + schema + ' CASCADE')


if __name__ == '__main__':
    main()

"""Paired loopback launcher for a native bundled Python application, not an installer."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import webbrowser
import certifi

RESOURCE_ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
if str(RESOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(RESOURCE_ROOT))
BUNDLE_ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else RESOURCE_ROOT


def user_data_dir(environ=None, platform=None):
    env = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    if platform == 'win32':
        return Path(env.get('LOCALAPPDATA') or Path.home() / 'AppData/Local') / 'Youji'
    if platform == 'darwin':
        return Path.home() / 'Library/Application Support/Youji'
    return Path(env.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'youji'


def read_provision(path):
    """Only explicitly provisioned settings; never import project .env or arbitrary env."""
    path = Path(path)
    if not path.exists():
        return {'schema_version': 1, 'deepseek_api_key': '', 'windtunnel_allow_live': False}
    if path.is_symlink() or path.stat().st_size > 16384:
        raise ValueError('Provision configuration is not a bounded regular file.')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate provision field.')
            result[key] = value
        return result
    config = json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique)
    if not isinstance(config, dict) or set(config) - {'schema_version', 'deepseek_api_key', 'windtunnel_allow_live'} or config.get('schema_version') != 1:
        raise ValueError('Unsupported provision configuration.')
    key = config.get('deepseek_api_key', '')
    live = config.get('windtunnel_allow_live', False)
    if not isinstance(key, str) or len(key) > 4096 or any(c.isspace() for c in key) or type(live) is not bool:
        raise ValueError('Invalid provision values.')
    return {'schema_version': 1, 'deepseek_api_key': key, 'windtunnel_allow_live': live}


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def child_environment(data_dir, port, config, bundle_root=BUNDLE_ROOT, inherited=None):
    source = os.environ if inherited is None else inherited
    allowed = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'HOME', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'LANG', 'LC_ALL', 'TMP', 'TEMP', 'TMPDIR'}
    env = {key: value for key, value in source.items() if key in allowed}
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1', YOUJI_IGNORE_PROJECT_ENV='1',
               SSL_CERT_FILE=certifi.where(),
               DATABASE_URL=str(Path(data_dir) / 'youji.sqlite'), PUBLIC_ORIGIN=f'http://127.0.0.1:{port}',
               DEEPSEEK_API_KEY=config['deepseek_api_key'], MODEL_ROUTES_JSON='{}', REGISTRATION_INVITE='',
               WINDTUNNEL_ALLOW_LIVE='true' if config['windtunnel_allow_live'] else 'false',
               PLAYWRIGHT_BROWSERS_PATH=str(Path(bundle_root) / 'browser'),
               YOUJI_CJK_FONT=str(Path(bundle_root) / 'assets/fonts/NotoSansCJKsc-Regular.otf'))
    return env


def service_command(service, port, data_dir, marker):
    prefix = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, str(Path(__file__).resolve())]
    return prefix + ['--service', service, '--port', str(port), '--data-dir', str(data_dir), '--worker-marker', str(marker)]


def offline_self_test(output):
    """Explicit synthetic offline fixture; no model, authentication or production writes."""
    import hashlib
    import io
    import zipfile
    from PIL import Image, ImageFont
    import imageio_ffmpeg
    from backend import media_exports, html_cards
    from backend.workflow import Run, digest
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    os.environ.update(DEEPSEEK_API_KEY='', YOUJI_IGNORE_PROJECT_ENV='1',
                      PLAYWRIGHT_BROWSERS_PATH=str(BUNDLE_ROOT / 'browser'),
                      YOUJI_CJK_FONT=str(BUNDLE_ROOT / 'assets/fonts/NotoSansCJKsc-Regular.otf'))
    font = ImageFont.truetype(media_exports.font_path(), 42)
    if bytes(font.getmask('有')) == bytes(font.getmask('迹')):
        raise RuntimeError('Chinese font glyphs unavailable.')
    content = {'selected_title':'中文便携安装离线验收', 'body':'第一步：资料只来自本地测试。\n第二步：中文图卡完整展示，不调用收费模型。', 'cta':'这是合成测试，不是真实创作者反馈。', 'tags':['离线测试']}
    run = Run('offline-fixture', 'offline-snapshot', context={'mode':'simulation'})
    run.drafts = [{'ref':'offline@1','content':content,'content_hash':digest(content),'snapshot_id':'offline-snapshot'}]
    run.accepted_ref = 'offline@1'
    run.acceptance = {'draft_ref':'offline@1','content_hash':digest(content),'snapshot_id':'offline-snapshot','mode':'reviewed'}
    run.run_status = 'SUCCEEDED'
    records = {}; artifacts = []
    for label, kind, template in [('pillow','images','classic'),('chromium','images','xhs-e'),('ffmpeg','video','classic')]:
        print('Offline fixture export: ' + label, flush=True)
        data, _, _ = media_exports.export_run(run, kind=kind, template=template)
        target = output / (label + '.zip'); target.write_bytes(data)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if archive.testzip() is not None or content['body'] not in archive.read('caption.txt').decode():
                raise RuntimeError('Export content mismatch.')
            pictures = [n for n in archive.namelist() if n.endswith('.png')]
            for name in pictures:
                with Image.open(io.BytesIO(archive.read(name))) as image:
                    image.load()
                    if image.size != (1080,1440) or len(image.getcolors(image.width*image.height) or []) < 2:
                        raise RuntimeError('Export image invalid.')
            if label == 'ffmpeg':
                video = output / 'video.mp4'; video.write_bytes(archive.read('video.mp4'))
                result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-i',str(video),'-f','null','-'],capture_output=True,timeout=90)
                if result.returncode:
                    raise RuntimeError('Video decoding failed.')
            records[label] = {'valid':True,'png_count':len(pictures),'sha256':hashlib.sha256(data).hexdigest()}
        artifacts.append(target.name)
    report = {'schema_version':1,'fixture':'synthetic_offline_confirmed_draft_in_memory','paid_model_calls':0,'production_writes':False,'font_glyphs_distinct':True,'checks':records,'artifacts':artifacts}
    (output/'self-test-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def run_service(args):
    if args.service == 'self-test':
        if not args.self_test_output:
            raise ValueError('Self-test requires an output directory.')
        offline_self_test(args.self_test_output)
        return
    if args.service in ('document-parser', 'word-parser'):
        # Static imports make the isolated parsers visible to the bundler.
        from backend import document_parser, word_parser
        (document_parser if args.service == 'document-parser' else word_parser).main()
        return
    # Static imports ensure PyInstaller collects these entry points and their dependencies.
    from backend import api, worker
    from backend.provider import load_config
    from backend.store import Store
    from backend.service import Service
    env = api.settings()
    config = load_config()
    if args.service == 'api':
        import uvicorn
        uvicorn.run(api.create_app(config=config), host='127.0.0.1', port=args.port, access_log=False)
    else:
        service = Service(Store(env['DATABASE_URL']), config, allow_windtunnel_live=env.get('WINDTUNNEL_ALLOW_LIVE') == 'true')
        instance = worker.Worker(service)
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: instance.stopped.set())
        instance.online()
        Path(args.worker_marker).write_text(json.dumps({'worker_id': instance.id}), encoding='utf-8')
        instance.run()


def ready(origin, database, marker):
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(origin + '/health', timeout=1) as response:
            data = json.load(response)
        if data.get('status') != 'ok' or data.get('database') != 'sqlite':
            return False
        worker_id = json.loads(Path(marker).read_text())['worker_id']
        with sqlite3.connect(str(database), timeout=1) as db:
            row = db.execute('SELECT heartbeat FROM runtime_workers WHERE id=?', (worker_id,)).fetchone()
        return bool(row and 0 <= time.time() - row[0] < 15)
    except (OSError, ValueError, KeyError, sqlite3.Error):
        return False


def stop_processes(processes):
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 8
    for process in processes:
        try:
            process.wait(timeout=max(.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)


def log_stream(stream, target, secrets, lock):
    try:
        for line in iter(stream.readline, ''):
            for value in secrets:
                if value:
                    line = line.replace(value, '[REDACTED]')
            with lock:
                target.write(line); target.flush()
    finally:
        stream.close()


def launch(args):
    data_dir = Path(args.data_dir or user_data_dir()).expanduser().absolute()
    if data_dir == RESOURCE_ROOT or RESOURCE_ROOT in data_dir.parents or data_dir == BUNDLE_ROOT:
        raise ValueError('User data must be outside the application directory.')
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt':
        data_dir.chmod(0o700)
    config = read_provision(args.config_path or BUNDLE_ROOT / 'provision.json')
    # Private config stays in user data; the installed directory remains read-only.
    private = data_dir / 'provision.json'
    if args.config_path is None and private.exists():
        config = read_provision(private)
    port = free_port(); origin = f'http://127.0.0.1:{port}'
    env = child_environment(data_dir, port, config)
    marker = data_dir / ('worker-ready-' + uuid.uuid4().hex + '.json')
    processes = []; threads = []; stop = threading.Event(); lock = threading.Lock(); log = None
    previous = {}
    log_path = data_dir / 'launcher.log'
    try:
        log = log_path.open('a', encoding='utf-8')
        if os.name != 'nt':
            log_path.chmod(0o600)
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, lambda *_: stop.set())
        for service in ('api', 'worker'):
            process = subprocess.Popen(service_command(service, port, data_dir, marker), cwd=str(data_dir), env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
            processes.append(process)
            thread = threading.Thread(target=log_stream, args=(process.stdout, log, [config['deepseek_api_key']], lock), daemon=True)
            thread.start(); threads.append(thread)
        deadline = time.monotonic() + args.timeout
        while not ready(origin, data_dir / 'youji.sqlite', marker):
            if stop.is_set() or any(p.poll() is not None for p in processes):
                raise RuntimeError('A service stopped before becoming ready.')
            if time.monotonic() >= deadline:
                raise RuntimeError('API and worker readiness timed out.')
            stop.wait(.2)
        if args.ready_file:
            Path(args.ready_file).write_text(json.dumps({'ready': True, 'origin': origin, 'api_pid': processes[0].pid, 'worker_pid': processes[1].pid}), encoding='utf-8')
        print('有迹已就绪：' + origin, flush=True)
        if not args.check and not args.no_browser:
            webbrowser.open(origin)
        if not args.check:
            missed_health = 0
            while not stop.wait(1):
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError('API or worker became unavailable.')
                missed_health = 0 if ready(origin, data_dir / 'youji.sqlite', marker) else missed_health + 1
                if missed_health >= 3:
                    raise RuntimeError('API or worker became unavailable.')
    except Exception as error:
        if log is not None:
            safe = {'A service stopped before becoming ready.', 'API and worker readiness timed out.', 'API or worker became unavailable.'}
            detail = str(error) if isinstance(error, RuntimeError) and str(error) in safe else type(error).__name__
            with lock:
                log.write('Launcher failure: ' + detail + '\n'); log.flush()
        raise
    finally:
        stop_processes(processes)
        for thread in threads:
            thread.join(timeout=3)
        if log is not None:
            log.close()
        marker.unlink(missing_ok=True)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--service', choices=('api', 'worker', 'document-parser', 'word-parser', 'self-test'))
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--worker-marker')
    parser.add_argument('--self-test-output')
    parser.add_argument('--data-dir')
    parser.add_argument('--config-path')
    parser.add_argument('--ready-file')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--timeout', type=float, default=45)
    args = parser.parse_args(argv)
    try:
        if args.service:
            if args.service in ('api', 'worker') and (not args.data_dir or not 1 <= args.port <= 65535 or not args.worker_marker):
                raise ValueError('Invalid internal service arguments.')
            run_service(args)
            return 0
        return launch(args)
    except Exception:
        # Deliberately omit exception strings and config; neither stderr nor UI may expose secrets.
        location = Path(args.data_dir or user_data_dir()).expanduser().absolute() / 'launcher.log'
        print('启动失败，两个服务已停止。请查看本机日志：' + str(location), file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())

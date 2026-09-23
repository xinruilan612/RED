"""Run an isolated, no-model-key teacher demo: python scripts/start_demo.py.

--check verifies dependencies without starting anything; --smoke starts both
processes, verifies HTTP and the exact worker heartbeat, then stops them.
"""
import argparse
from contextlib import closing
import importlib.metadata
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
from urllib.request import ProxyHandler, build_opener
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def dependencies(root=ROOT):
    if sys.version_info < (3, 12):
        raise RuntimeError('Python 3.12 or newer is required.')
    missing = []
    for line in (root / 'requirements.txt').read_text(encoding='utf-8').splitlines():
        name, separator, expected = line.strip().partition('==')
        if not separator:
            continue
        try:
            if importlib.metadata.version(name) != expected:
                missing.append(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
    if missing:
        raise RuntimeError('Missing or mismatched dependencies: ' + ', '.join(missing) +
                           '. Run this Python with -m pip install -r requirements.txt.')


def demo_environment(root, port, environ=None):
    if type(port) is not int or not 1024 <= port <= 65535 or port == 8765:
        raise ValueError('Choose a port from 1024 to 65535, excluding the existing site port 8765.')
    root = Path(root).resolve()
    database = root / 'runtime' / 'review-demo' / 'demo.sqlite'
    if database.resolve() != database:
        raise ValueError('Demo storage must not use symlinks or junctions outside its own path.')
    env = dict(os.environ if environ is None else environ)
    env.update(DATABASE_URL=str(database), PUBLIC_ORIGIN=f'http://127.0.0.1:{port}',
               DEEPSEEK_API_KEY='', MODEL_ROUTES_JSON='{}', REGISTRATION_INVITE='',
               PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(root),
               YOUJI_DEMO_WORKER_ID=uuid4().hex)
    return env, database


def check_port(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if os.name == 'nt':
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(('127.0.0.1', port))
        except OSError as error:
            raise RuntimeError(f'Port {port} is occupied or unavailable. Choose --port; no existing process was stopped.') from error


def stop_children(children):
    """Only stop handles returned by this launcher's own Popen calls."""
    for _, process in children:
        try:
            if process.poll() is None:
                process.terminate()
        except ProcessLookupError:
            pass  # The owned process exited between poll and terminate.
    for _, process in children:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        finally:
            if process.stdin:
                process.stdin.close()


def assert_running(children):
    for role, process in children:
        code = process.poll()
        if code is not None:
            raise RuntimeError(f'{role} exited unexpectedly (code {code}); see this launch\'s log files.')


def ready(origin, database, worker_id):
    try:
        with build_opener(ProxyHandler({})).open(origin + '/health', timeout=0.5) as response:
            health = json.load(response)
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=0.5)) as db:
            heartbeat = db.execute('SELECT heartbeat FROM runtime_workers WHERE id=?', (worker_id,)).fetchone()
        return health.get('status') == 'ok' and health.get('database') == 'sqlite' and bool(
            heartbeat and time.time() - heartbeat[0] < 5)
    except (OSError, ValueError, sqlite3.Error):
        return False


def watch_parent():
    """An ownership pipe prevents orphaned services after abrupt launcher exit."""
    sys.stdin.buffer.read()
    os._exit(0)


def child(role, port):
    expected, _ = demo_environment(ROOT, port, {})
    for key in ('DATABASE_URL', 'PUBLIC_ORIGIN', 'DEEPSEEK_API_KEY', 'MODEL_ROUTES_JSON', 'REGISTRATION_INVITE'):
        if os.environ.get(key) != expected[key]:
            raise RuntimeError('Internal child mode requires the isolated demo environment.')
    threading.Thread(target=watch_parent, daemon=True).start()
    sys.path.insert(0, str(ROOT))
    from backend.provider import Config
    from backend.store import Store
    store, config = Store(os.environ['DATABASE_URL']), Config()
    if role == 'api':
        import uvicorn
        from backend.api import create_app
        app = create_app(store, config, origin=os.environ['PUBLIC_ORIGIN'], invite='',
                         settings_override=dict(os.environ), session_cookie='youji_review_session')
        uvicorn.run(app, host='127.0.0.1', port=port, access_log=False)
    else:
        from backend.service import Service
        from backend.worker import Worker
        worker = Worker(Service(store, config))
        worker.id = os.environ['YOUJI_DEMO_WORKER_ID']
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: worker.stopped.set())
        worker.run()


def run(port=8786, smoke=False, root=ROOT, timeout=30):
    env, database = demo_environment(root, port)
    check_port(port)
    database.parent.mkdir(parents=True, exist_ok=True)
    children, logs = [], []
    stamp = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8]
    try:
        for role in ('api', 'worker'):
            log_path = database.parent / f'{stamp}-{role}.log'
            log = log_path.open('x', encoding='utf-8')
            logs.append(log)
            print(f'{role} log: {log_path}', flush=True)
            options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
            process = subprocess.Popen([sys.executable, str(ROOT / 'scripts' / 'start_demo.py'),
                                        '--child', role, '--port', str(port)],
                                       cwd=root, env=env, stdin=subprocess.PIPE, stdout=log,
                                       stderr=subprocess.STDOUT, **options)
            children.append((role, process))
        deadline = time.monotonic() + timeout
        while True:
            assert_running(children)
            if ready(env['PUBLIC_ORIGIN'], database, env['YOUJI_DEMO_WORKER_ID']):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('Startup timed out: API or worker did not become ready; see the log files.')
            time.sleep(0.2)
        print(f'Demo ready: {env["PUBLIC_ORIGIN"]}/ (simulation only; no API key)', flush=True)
        print(f'Data retained: {database}. Ctrl+C stops only this demo.', flush=True)
        stable_until = time.monotonic() + 1
        while not smoke or time.monotonic() < stable_until:
            assert_running(children)
            time.sleep(0.2)
        assert_running(children)
        print('SMOKE PASS: HTTP health and this worker heartbeat verified.', flush=True)
    finally:
        try:
            stop_children(children)
        finally:
            for log in logs:
                log.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8786)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--check', action='store_true', help='Check Python and pinned dependencies only.')
    modes.add_argument('--smoke', action='store_true', help='Start, verify, and stop the isolated demo.')
    parser.add_argument('--child', choices=('api', 'worker'), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        child(args.child, args.port)
        return 0
    previous = signal.getsignal(signal.SIGTERM)
    def request_stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, request_stop)
    try:
        dependencies()
        if args.check:
            print('CHECK PASS: Python and all pinned dependencies are available; no service or database started.')
        else:
            run(args.port, args.smoke)
        return 0
    except KeyboardInterrupt:
        print('Demo stopped. Existing data and unrelated services were left untouched.')
        return 0
    except (RuntimeError, ValueError, OSError) as error:
        print('Demo could not start: ' + str(error), file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == '__main__':
    raise SystemExit(main())

"""Foreground Windows portable launcher; never reads the author's configuration.

Bundle layout: app/ (this checkout), python/ (embedded CPython), data/ (created
on first use). The application and its durable Worker share only data/teacher.sqlite.
"""
import argparse
from contextlib import ExitStack, closing
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import struct
import subprocess
import sys
import threading
import time
from urllib.request import ProxyHandler, build_opener
import webbrowser


class LaunchError(RuntimeError):
    pass


def layout(script=None):
    app = Path(script or __file__).resolve().parents[1]
    bundle = app.parent
    interpreter = bundle / 'python' / 'python.exe'
    if app.name != 'app' or not (app / 'backend' / 'api.py').is_file() or not interpreter.is_file():
        raise LaunchError('运行包不完整。请先解压整个 ZIP，再双击根目录的一键启动.cmd；不要单独运行脚本。')
    # API/provider settings always read app/.env if it exists. Refuse rather than
    # inspect, delete, copy, or accidentally use an author's old configuration.
    if (app / '.env').exists() or (app / '.env').is_symlink():
        raise LaunchError('教师包 app 中发现 .env。为避免读取原数据库或密钥，已停止；请使用未混入旧配置的完整运行包。')
    return app, bundle, interpreter


def child_environment(data, port, source=None):
    source = os.environ if source is None else source
    # Explicit OS-only allowlist: no inherited DB, model, proxy, connector,
    # Python startup/site hooks, credentials or tracing/exporter configuration.
    allowed = {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'USERPROFILE',
               'APPDATA', 'LOCALAPPDATA', 'PROGRAMDATA', 'OS', 'NUMBER_OF_PROCESSORS'}
    env = {key: value for key, value in source.items() if key.upper() in allowed}
    env.update(DATABASE_URL=str((data / 'teacher.sqlite').resolve()),
               PUBLIC_ORIGIN=f'http://127.0.0.1:{port}', REGISTRATION_INVITE='',
               DEEPSEEK_API_KEY='', MODEL_ROUTES_JSON='{}', MODEL_CREDENTIAL_KEY='',
               WINDTUNNEL_ALLOW_LIVE='false', YOUJI_EMBEDDING_MODEL_PATH='off',
               PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    return env


def available_port(first=8890, count=20):
    for port in range(first, first + count):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                continue
            return port
    raise LaunchError(f'本机端口 {first}–{first + count - 1} 均不可用。请关闭占用端口的软件后重新启动；没有停止任何其他进程。')


def prepare_data(bundle):
    data = bundle / 'data'
    for path in (data, data / 'teacher.sqlite', data / 'launcher.lock'):
        if path.is_symlink() or path.is_junction():
            raise LaunchError('data 路径指向其他位置，已停止以保护原有数据；请在普通本地文件夹完整解压运行包。')
    data.mkdir(exist_ok=True)
    (data / 'logs').mkdir(exist_ok=True)
    return data


class Children:
    """A kill-on-close job contains only processes created by this launcher."""
    def __init__(self):
        from backend import windows_reader_process as win
        self.win, self.processes, self.job = win, [], None
        job = win._create_job(None, None)
        if not job:
            raise OSError('Cannot create the launcher process container')
        limits = win.ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not win._set_job(job, 9, win.c.byref(limits), win.c.sizeof(limits)):
            win._close(job)
            raise OSError('Cannot protect launcher child processes')
        self.job = job

    def start(self, command, *, cwd, env, log):
        # The gate runs before the actual service. Closing the window before job
        # assignment only closes stdin: the gate exits without spawning anything.
        executable = getattr(sys, '_base_executable', sys.executable)
        child = subprocess.Popen(
            [executable, '-I', '-S', '-X', 'utf8', '-B', '-c', self.win.GATED_READER, *command],
            cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.processes.append(child)
        try:
            if not self.win._assign_job(self.job, int(child._handle)):
                raise OSError('Cannot bind a service to the launcher process container')
            child.stdin.write(b'1')
            child.stdin.flush()
        finally:
            child.stdin.close()
        return child

    def close(self):
        if self.job is not None:
            self.win._close(self.job)
            self.job = None
        for child in self.processes:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)


def ready(url, database, started):
    try:
        # Ignore all machine/browser proxy configuration for this local probe.
        with build_opener(ProxyHandler({})).open(url + '/health', timeout=.5) as response:
            value = json.loads(response.read(2048))
        if not isinstance(value, dict) or value.get('status') != 'ok' or value.get('database') != 'sqlite':
            return False
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=.5)) as db:
            heartbeat = db.execute('SELECT MAX(heartbeat) FROM runtime_workers').fetchone()[0]
        return heartbeat is not None and heartbeat >= started
    except (OSError, ValueError, sqlite3.Error):
        return False


def write_state(data, status, url, children):
    record = {'status': status, 'url': url, 'launcher_pid': os.getpid(),
              'child_pids': [child.pid for child in children], 'updated_at': time.time()}
    temporary = data / 'launcher.json.tmp'
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
    os.replace(temporary, data / 'launcher.json')


def serve(app, bundle, interpreter, *, no_browser=False, stop=None, startup_timeout=60):
    from backend.file_lock import exclusive_file_lock
    stop = stop or threading.Event()
    data = prepare_data(bundle)
    try:
        with ExitStack() as stack:
            try:
                stack.enter_context(exclusive_file_lock(data / 'launcher.lock'))
            except BlockingIOError:
                print('教师版已经在运行。请使用原来的控制窗口和浏览器；本次没有重复启动。', flush=True)
                return 0
            port = available_port()
            url = f'http://127.0.0.1:{port}'
            env = child_environment(data, port)
            logs = [stack.enter_context((data / 'logs' / name).open('ab', buffering=0))
                    for name in ('api.log', 'worker.log')]
            children = Children()
            # Registered after logs so child handles close before log handles.
            stack.callback(children.close)
            started = time.time()
            try:
                for module, extra, log in (
                    ('backend.api', ['--host', '127.0.0.1', '--port', str(port)], logs[0]),
                    ('backend.worker', [], logs[1]),
                ):
                    children.start([str(interpreter), '-X', 'utf8', '-B', '-m', module, *extra],
                                   cwd=app, env=env, log=log)
                write_state(data, 'starting', url, children.processes)
                print('正在启动教师版，请保持这个窗口打开。首次启动会建立本包独立数据库。', flush=True)
                deadline = time.monotonic() + startup_timeout
                announced = False
                while not stop.is_set():
                    if any(child.poll() is not None for child in children.processes):
                        raise LaunchError('网站或后台进程已退出。请查看 data/logs/api.log 和 worker.log；原数据保留。端口竞争时可重新启动。')
                    if not announced:
                        if ready(url, Path(env['DATABASE_URL']), started):
                            announced = True
                            write_state(data, 'ready', url, children.processes)
                            print(f'教师版已就绪：{url}/\n数据仅保存在：{data}\n按 Ctrl+C 或关闭本窗口停止本包进程。\n停止窗口不等于取消已保存任务；已开启真实任务请先在网页取消。', flush=True)
                            if not no_browser:
                                try:
                                    if not webbrowser.open(url + '/'):
                                        print('未能自动打开浏览器，请复制上方网址打开。', flush=True)
                                except Exception:
                                    print('未能自动打开浏览器，请复制上方网址打开。', flush=True)
                        elif time.monotonic() >= deadline:
                            raise LaunchError('启动超时：网站或 Worker 尚未就绪。已停止本次进程；请查看 data/logs，确认运行包已完整解压且可写。')
                    stop.wait(.2)
                return 0
            finally:
                write_state(data, 'stopped', url, children.processes)
    except PermissionError as error:
        raise LaunchError('无法写入运行包的 data 文件夹。请完整解压到本人有写入权限的本地文件夹后重试，不需要管理员运行。') from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true', help='do not open a browser automatically')
    args = parser.parse_args(argv)
    if os.name != 'nt' or struct.calcsize('P') != 8:
        print('此运行包需要 Windows 10/11 64 位系统。', file=sys.stderr)
        return 1
    stop = threading.Event()
    previous = signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        app, bundle, interpreter = layout()
        return serve(app, bundle, interpreter, no_browser=args.no_browser, stop=stop)
    except (LaunchError, OSError) as error:
        # Do not print an inherited environment, connection string or traceback.
        message = str(error) if isinstance(error, LaunchError) else '运行包启动失败，数据未删除。请检查完整解压、文件权限及 data/logs。'
        print(message, file=sys.stderr, flush=True)
        return 1
    finally:
        signal.signal(signal.SIGINT, previous)


if __name__ == '__main__':
    raise SystemExit(main())

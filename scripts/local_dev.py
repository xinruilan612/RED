"""Cross-platform local setup and paired API/Worker launcher (no paid calls)."""
import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def python_path(root=ROOT, windows=None):
    windows = os.name == 'nt' if windows is None else windows
    return root / 'runtime' / 'venv' / ('Scripts/python.exe' if windows else 'bin/python')


def setup(root=ROOT):
    if sys.version_info < (3, 12):
        raise RuntimeError('Python 3.12 or newer is required.')
    interpreter = python_path(root)
    if not interpreter.exists():
        try:
            import venv
        except ImportError:
            raise RuntimeError('Creating a development environment requires the full Python 3.12+ installation with venv; the portable embedded Python cannot create it. Use the portable package launcher instead, or run setup with full Python.') from None
        venv.EnvBuilder(with_pip=True).create(root / 'runtime' / 'venv')
    subprocess.run([str(interpreter), '-m', 'pip', 'install', '-r', str(root / 'requirements.txt')], check=True, cwd=root)
    target = root / '.env'
    if not target.exists():
        shutil.copyfile(root / '.env.example', target)
        print('Created .env. Set DATABASE_URL for your local PostgreSQL database.')
    else:
        print('Existing .env preserved.')
    print('Setup complete. Next: edit .env, then run doctor and start.')


def endpoint(env):
    origin = env.get('PUBLIC_ORIGIN', 'http://127.0.0.1:8765')
    try:
        parsed = urlsplit(origin)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username:
            raise ValueError()
        return '127.0.0.1', parsed.port or 80, origin.rstrip('/')
    except ValueError:
        raise RuntimeError('Local launcher requires PUBLIC_ORIGIN=http://127.0.0.1:8765 (or another local port).') from None


def doctor():
    try:
        from backend.api import settings
        from backend.database import connect
        import langgraph.checkpoint.postgres  # noqa: F401
        import pypdf  # noqa: F401
    except ImportError:
        raise RuntimeError('Dependencies missing. Run setup first.') from None
    env = settings()
    endpoint(env)
    database = env.get('DATABASE_URL', '')
    if not database.startswith(('postgresql://', 'postgres://')):
        raise RuntimeError('Set DATABASE_URL to your PostgreSQL database in .env.')
    try:
        with connect(database) as db:
            db.execute('SELECT 1').fetchone()
    except Exception:
        # Driver exceptions may include credentials/connection strings.
        raise RuntimeError('PostgreSQL connection failed. Check service, database, username and password in .env; details are not printed.') from None
    print('OK: dependencies, local URL and PostgreSQL connection.')
    print('DeepSeek: configured.' if env.get('DEEPSEEK_API_KEY') else 'DeepSeek: not configured; simulation is available.')
    return env


def stop_children(children):
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


def serve(env):
    host, port, origin = endpoint(env)
    with socket.socket() as probe:
        try:
            probe.bind((host, port))
        except OSError:
            raise RuntimeError('Port is already in use. Stop the previous server or change PUBLIC_ORIGIN.') from None
    children = []
    try:
        for args in (['backend.api', '--host', host, '--port', str(port)], ['backend.worker']):
            children.append(subprocess.Popen([sys.executable, '-m', *args], cwd=ROOT, env={**os.environ, 'PYTHONUTF8':'1'}))
        print(f'Website: {origin}/  (wait for API startup). Keep this window open; Ctrl+C stops both processes.', flush=True)
        while True:
            if any(child.poll() is not None for child in children):
                raise RuntimeError('API or Worker exited. Both processes have been stopped; inspect startup output.')
            time.sleep(.3)
    except KeyboardInterrupt:
        print('\nStopping local services.')
    finally:
        stop_children(children)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['setup', 'doctor', 'start'], nargs='?', default='start')
    args = parser.parse_args()
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        if args.command == 'setup':
            setup()
            return 0
        interpreter = python_path()
        if not interpreter.exists():
            raise RuntimeError('Virtual environment missing. Run setup first.')
        if Path(sys.prefix).resolve() != (ROOT / 'runtime' / 'venv').resolve():
            return subprocess.call([str(interpreter), str(Path(__file__).resolve()), args.command], cwd=ROOT)
        env = doctor()
        if args.command == 'start':
            serve(env)
        return 0
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(str(error) if isinstance(error, RuntimeError) else 'Setup/start failed. Check the output above; no configuration file was overwritten.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

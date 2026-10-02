"""GitHub-hosted CI only: own disposable PostgreSQL cluster and zero-skip gates.

No dotenv loading, system services, existing databases, or model credentials.
`--dry-run` is safe on a developer machine and never starts a process/database.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
NODE_TESTS = (
    'frontend_execution', 'frontend_account_profile', 'frontend_account_form',
    'frontend_reader_bridge', 'frontend_guidance',
)
FRONTEND_SCRIPTS = (
    'app', 'operations', 'account', 'account_profile', 'auth', 'knowledge',
    'windtunnel', 'trials', 'guidance',
)
BINARIES = ('postgres', 'initdb', 'pg_ctl', 'createdb', 'psql')
TEXT_SUFFIXES = {'.py', '.js', '.cjs', '.mjs', '.md', '.json', '.html', '.css',
                 '.txt', '.yaml', '.yml', '.toml', '.sh', '.command', '.cmd'}


def ci_context(environ, root=ROOT):
    if environ.get('GITHUB_ACTIONS') != 'true' or environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise RuntimeError('Database startup is allowed only on GitHub-hosted Actions runners.')
    workspace = Path(environ.get('GITHUB_WORKSPACE', ''))
    temporary = Path(environ.get('RUNNER_TEMP', ''))
    if not workspace.is_absolute() or workspace.resolve() != root.resolve():
        raise RuntimeError('GITHUB_WORKSPACE must be this checked-out repository.')
    if not temporary.is_absolute() or not temporary.is_dir() or temporary.is_symlink():
        raise RuntimeError('RUNNER_TEMP must be an existing absolute non-symlink directory.')
    temporary = temporary.resolve()
    if temporary == Path(temporary.anchor) or temporary == root.resolve() or temporary in root.resolve().parents or root.resolve() in temporary.parents:
        raise RuntimeError('RUNNER_TEMP must be separate from the workspace and filesystem root.')
    if (root / '.env').exists():
        raise RuntimeError('Refusing CI in a checkout containing .env; no configuration was read.')
    return temporary


def test_environment(environ):
    # libpq's preinstalled Windows PGDATA/PGPASSWORD must not select its service.
    result = {key: value for key, value in environ.items()
              if not key.upper().startswith('PG')
              and key.upper() not in {'DATABASE_URL', 'TEST_DATABASE_URL', 'FIXTURE_DATABASE_URL', 'MODEL_ROUTES_JSON'}
              and not key.upper().endswith(('_API_KEY', '_TOKEN', '_SECRET', '_PASSWORD'))}
    result.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
                  PYTHONDONTWRITEBYTECODE='1', DEEPSEEK_API_KEY='',
                  LANGSMITH_TRACING='false', LANGCHAIN_TRACING_V2='false')
    return result


def command(args, *, environ, capture=False, timeout=60):
    return subprocess.run([str(arg) for arg in args], cwd=ROOT, env=environ,
                          check=True, timeout=timeout, capture_output=capture,
                          text=True, encoding='utf-8', errors='replace')


def postgres_binaries(environ, major):
    if major not in (16, 17):
        raise RuntimeError('CI expects PostgreSQL major 16 or 17, not an unreviewed upgrade.')
    candidates = [Path(value) for key in ('RED_CI_PG_BIN', 'PGBIN')
                  if (value := environ.get(key))]
    candidates.extend((Path(f'/usr/lib/postgresql/{major}/bin'),
                       Path(f'/opt/homebrew/opt/postgresql@{major}/bin'),
                       Path(f'/usr/local/opt/postgresql@{major}/bin'),
                       Path(f'C:/Program Files/PostgreSQL/{major}/bin')))
    found = shutil.which('initdb')
    if found:
        candidates.append(Path(found).parent)
    suffix = '.exe' if os.name == 'nt' else ''
    clean_env = test_environment(environ)
    for folder in candidates:
        paths = {name: folder / (name + suffix) for name in BINARIES}
        if not all(path.is_file() for path in paths.values()):
            continue
        versions = [command([path, '--version'], environ=clean_env, capture=True).stdout.strip()
                    for path in paths.values()]
        if not all(re.search(rf'\(PostgreSQL\) {major}\.', version) for version in versions):
            raise RuntimeError('PostgreSQL binaries do not all match the selected major.')
        print('PostgreSQL binaries: ' + versions[0], flush=True)
        return paths, versions[0]
    raise RuntimeError('PostgreSQL binaries missing. CI never falls back to an existing service.')


def free_loopback_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class TemporaryPostgres:
    def __init__(self, temporary, binaries, environ):
        self.base = temporary.resolve()
        self.binaries = binaries
        self.environ = environ
        self.path = Path(tempfile.mkdtemp(prefix='red-ci-pg-', dir=self.base))
        self.data = self.path / 'data'
        self.marker = uuid4().hex
        (self.path / '.red-ci-owned').write_text(self.marker, encoding='utf-8')
        self.port = free_loopback_port()
        self.attempted_start = False

    def validate_owned(self):
        path = self.path.resolve()
        marker = self.path / '.red-ci-owned'
        if self.path.is_symlink() or path.parent != self.base or not path.name.startswith('red-ci-pg-') or self.data.is_symlink() or self.data.resolve() != path / 'data':
            raise RuntimeError('Temporary cluster ownership/path validation failed.')
        if not marker.is_file() or marker.is_symlink() or marker.read_text(encoding='utf-8') != self.marker:
            raise RuntimeError('Temporary cluster ownership marker missing or changed.')

    def pg(self, name, *args, capture=False):
        self.validate_owned()
        return command([self.binaries[name], *args], environ=self.environ, capture=capture)

    def validate_pid(self):
        pid = (self.data / 'postmaster.pid').read_text(encoding='utf-8').splitlines()
        if len(pid) < 4 or not pid[0].isdigit() or int(pid[0]) <= 0 or Path(pid[1]).resolve() != self.data.resolve() or pid[3] != str(self.port):
            raise RuntimeError('Started cluster identity does not match its private data directory/port.')

    def start(self):
        self.pg('initdb', '-D', self.data, '--username=red_ci', '--encoding=UTF8',
                '--no-locale', '--auth-local=trust', '--auth-host=trust')
        # A file in our brand-new cluster avoids platform-dependent -o quoting.
        with (self.data / 'postgresql.conf').open('a', encoding='utf-8') as config:
            config.write(f"\nlisten_addresses = '127.0.0.1'\nport = {self.port}\nunix_socket_directories = ''\n")
        self.attempted_start = True
        self.pg('pg_ctl', '-D', self.data, '-l', self.path / 'postgres.log', '-w', '-t', '30', 'start')
        self.validate_pid()
        connection = ('-h', '127.0.0.1', '-p', str(self.port), '-U', 'red_ci')
        actual = self.pg('psql', *connection, '-X', '-A', '-t', '-v', 'ON_ERROR_STOP=1',
                         '-d', 'postgres', '-c', 'SHOW data_directory; SHOW listen_addresses; SHOW port;', capture=True).stdout.splitlines()
        if len(actual) != 3 or Path(actual[0]).resolve() != self.data.resolve() or actual[1:] != ['127.0.0.1', str(self.port)]:
            raise RuntimeError('Refusing to create a database on an unverified server.')
        self.pg('createdb', *connection, '--encoding=UTF8', 'red_ci_test')
        return f'postgresql://red_ci@127.0.0.1:{self.port}/red_ci_test'

    def close(self):
        self.validate_owned()
        if self.attempted_start and (self.data / 'postmaster.pid').exists():
            # No system service control or broad PID/process kill is ever used.
            self.validate_pid()
            self.pg('pg_ctl', '-D', self.data, '-w', '-t', '30', '-m', 'fast', 'stop')
            if (self.data / 'postmaster.pid').exists():
                raise RuntimeError('Cluster stop was not confirmed; preserving its temporary directory.')
        self.validate_owned()
        shutil.rmtree(self.path)


@contextmanager
def replaced_environment(environ):
    previous = dict(os.environ)
    os.environ.clear()
    os.environ.update(environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


def run_python_tests():
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped or result.testsRun == 0:
        raise RuntimeError(f'Python gate failed: {result.testsRun} tests, {len(result.failures)} failures, '
                           f'{len(result.errors)} errors, {len(result.skipped)} skips.')
    return result.testsRun


def check_utf8(environ):
    names = command(['git', 'ls-files', '-z'], environ=environ, capture=True).stdout.split('\0')
    checked = 0
    for name in filter(None, names):
        path = ROOT / name
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {'.env.example', '.gitattributes', '.gitignore'}:
            path.read_text(encoding='utf-8-sig')
            checked += 1
    if not checked:
        raise RuntimeError('UTF-8 gate found no tracked text files.')
    print(f'UTF-8: {checked} tracked text files.', flush=True)
    return checked


def run_gates(environ):
    command([sys.executable, '-m', 'pip', 'check'], environ=environ)
    command(['git', 'diff', '--check'], environ=environ)
    checked = check_utf8(environ)
    count = run_python_tests()
    command(['node', '--test', *[f'tests/{name}.test.js' for name in NODE_TESTS]], environ=environ, timeout=120)
    for name in FRONTEND_SCRIPTS:
        command(['node', '--check', f'frontend/{name}.js'], environ=environ)
    command([sys.executable, 'scripts/local_dev.py', '--help'], environ=environ)
    return {'python_tests': count, 'python_skipped': 0, 'node_test_files': len(NODE_TESTS),
            'js_syntax_files': len(FRONTEND_SCRIPTS), 'utf8_files': checked,
            'dependency_check': 'passed', 'whitespace_check': 'passed', 'launcher_help': 'passed'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    if args.dry_run:
        print(json.dumps({'dry_run': True, 'database_started': False, 'requires': 'GitHub-hosted Actions',
                          'python': '3.12', 'node': '22', 'node_test_files': len(NODE_TESTS),
                          'js_syntax_files': len(FRONTEND_SCRIPTS), 'allow_skips': False}))
        return 0
    cluster = None
    try:
        original = dict(os.environ)
        temporary = ci_context(original)
        if sys.version_info[:2] != (3, 12):
            raise RuntimeError('This acceptance matrix requires Python 3.12.')
        major = int(original.get('RED_CI_PG_MAJOR', '0'))
        binaries, version = postgres_binaries(original, major)
        environ = test_environment(original)
        node_version = command(['node', '--version'], environ=environ, capture=True).stdout.strip()
        if not node_version.startswith('v22.'):
            raise RuntimeError('This acceptance matrix requires Node 22.')
        cluster = TemporaryPostgres(temporary, binaries, environ)
        url = cluster.start()
        environ.update(TEST_DATABASE_URL=url, DATABASE_URL=url)
        print(f'Environment: {platform.system()} {platform.machine()}, Python {platform.python_version()}', flush=True)
        print(node_version, flush=True)
        with replaced_environment(environ):
            results = run_gates(environ)
        results.update(postgresql=version, os=platform.system(), architecture=platform.machine(),
                       python=platform.python_version(), node=node_version,
                       real_model_calls=False, platform_publication=False)
        finished = cluster
        cluster = None
        finished.close()
        print('CI acceptance: ' + json.dumps(results), flush=True)
        summary = original.get('GITHUB_STEP_SUMMARY')
        if summary:
            with Path(summary).open('a', encoding='utf-8') as output:
                output.write('## Cross-platform acceptance\n\n```json\n' + json.dumps(results, indent=2) + '\n```\n')
        return 0
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'CI acceptance failed: {error}', file=sys.stderr)
        return 1
    finally:
        if cluster is not None:
            cluster.close()


if __name__ == '__main__':
    raise SystemExit(main())

"""Portable-launcher isolation and real owned-process cleanup; no paid requests."""
import io
from contextlib import closing
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backend.file_lock import exclusive_file_lock
from scripts import teacher_launcher as launcher


ROOT = Path(__file__).resolve().parents[1]


class PortableLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='teacher test ')
        self.addCleanup(self.temp.cleanup)
        self.bundle = Path(self.temp.name) / '有迹 教师版'
        self.app = self.bundle / 'app'
        (self.app / 'backend').mkdir(parents=True)
        (self.app / 'backend' / 'api.py').touch()
        (self.app / 'scripts').mkdir()
        self.script = self.app / 'scripts' / 'teacher_launcher.py'
        (self.bundle / 'python').mkdir()
        self.python = self.bundle / 'python' / 'python.exe'
        self.python.touch()

    def test_complete_layout_handles_spaces_and_chinese_without_creating_data(self):
        self.assertEqual(launcher.layout(self.script), (self.app, self.bundle, self.python))
        self.assertFalse((self.bundle / 'data').exists())

    def test_incomplete_package_and_old_env_are_rejected_without_reading_secrets(self):
        self.python.unlink()
        with self.assertRaises(launcher.LaunchError):
            launcher.layout(self.script)
        self.python.touch()
        (self.app / '.env').write_text('PRIVATE=never-read', encoding='utf-8')
        with patch.object(Path, 'read_text', side_effect=AssertionError('must not read .env')):
            with self.assertRaisesRegex(launcher.LaunchError, '.env'):
                launcher.layout(self.script)

    def test_child_environment_excludes_inherited_secrets_and_python_hooks(self):
        source = {'SYSTEMROOT': 'C:/Windows', 'TEMP': 'C:/Temp', 'PATH': 'bad-path',
                  'DATABASE_URL': 'original-database', 'DEEPSEEK_API_KEY': 'old-key',
                  'MODEL_CREDENTIAL_KEY': 'old-master-key', 'OPENAI_API_KEY': 'old-other-key',
                  'ANTHROPIC_API_KEY': 'old-key', 'XHS_COOKIE': 'old-cookie',
                  'HTTP_PROXY': 'old-proxy', 'PYTHONPATH': 'old-hook', 'PYTHONHOME': 'old-home',
                  'LANGSMITH_API_KEY': 'old-trace-key'}
        env = launcher.child_environment(self.bundle / 'data', 8892, source)
        self.assertEqual(env['DATABASE_URL'], str(self.bundle / 'data' / 'teacher.sqlite'))
        self.assertEqual(env['PUBLIC_ORIGIN'], 'http://127.0.0.1:8892')
        self.assertEqual(env['DEEPSEEK_API_KEY'], '')
        self.assertEqual(env['MODEL_CREDENTIAL_KEY'], '')
        self.assertEqual(env['MODEL_ROUTES_JSON'], '{}')
        self.assertEqual(env['WINDTUNNEL_ALLOW_LIVE'], 'false')
        self.assertEqual(env['YOUJI_EMBEDDING_MODEL_PATH'], 'off')
        self.assertEqual(env['SYSTEMROOT'], 'C:/Windows')
        self.assertFalse(any(value.startswith('old-') for value in env.values()))
        self.assertTrue({'PATH', 'PYTHONPATH', 'PYTHONHOME', 'OPENAI_API_KEY', 'XHS_COOKIE',
                         'LANGSMITH_API_KEY', 'HTTP_PROXY'}.isdisjoint(env))
        self.assertEqual(source['DEEPSEEK_API_KEY'], 'old-key')

    def test_existing_teacher_database_is_preserved_and_data_is_created_only_on_start(self):
        data = launcher.prepare_data(self.bundle)
        database = data / 'teacher.sqlite'
        database.write_bytes(b'existing-private-fixture')
        self.assertEqual(launcher.prepare_data(self.bundle), data)
        self.assertEqual(database.read_bytes(), b'existing-private-fixture')
        self.assertTrue((data / 'logs').is_dir())

    def test_occupied_port_is_not_reused_and_exhaustion_is_explained(self):
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            port = occupied.getsockname()[1]
            with self.assertRaisesRegex(launcher.LaunchError, '均不可用'):
                launcher.available_port(port, 1)
        with patch.object(launcher.socket, 'socket') as socket_type:
            probe = socket_type.return_value.__enter__.return_value
            probe.bind.side_effect = [OSError('busy'), None]
            self.assertEqual(launcher.available_port(8890, 2), 8891)
            self.assertEqual(probe.bind.call_args_list[1].args, (('127.0.0.1', 8891),))

    def test_readiness_requires_sqlite_api_and_new_worker_heartbeat(self):
        data = launcher.prepare_data(self.bundle)
        database = data / 'teacher.sqlite'
        with closing(sqlite3.connect(database)) as db:
            db.execute('CREATE TABLE runtime_workers (heartbeat REAL)')
            db.execute('INSERT INTO runtime_workers VALUES (100)')
            db.commit()
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"status":"ok","database":"sqlite"}'
        with patch.object(launcher, 'build_opener') as opener:
            opener.return_value.open.return_value = response
            self.assertTrue(launcher.ready('http://127.0.0.1:8890', database, 99))
            self.assertFalse(launcher.ready('http://127.0.0.1:8890', database, 101))
            response.read.return_value = b'{"status":"ok","database":"postgresql"}'
            self.assertFalse(launcher.ready('http://127.0.0.1:8890', database, 99))
            response.read.return_value = b'[]'
            self.assertFalse(launcher.ready('http://127.0.0.1:8890', database, 99))
        self.assertFalse(launcher.ready('http://127.0.0.1:0', database, 99))

    def fake_children(self, exit_code=None):
        children = Mock(processes=[])
        def start(*args, **kwargs):
            child = Mock(pid=100 + len(children.processes))
            child.poll.return_value = exit_code
            children.processes.append(child)
            return child
        children.start.side_effect = start
        return children

    def test_two_services_share_only_package_database_and_no_browser_mode(self):
        children, stop = self.fake_children(), threading.Event()
        def health(*args):
            stop.set()
            return True
        with patch.object(launcher, 'Children', return_value=children), \
             patch.object(launcher, 'available_port', return_value=8891), \
             patch.object(launcher, 'ready', side_effect=health), \
             patch.object(launcher.webbrowser, 'open') as browser, patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(launcher.serve(self.app, self.bundle, self.python, no_browser=True, stop=stop), 0)
        self.assertEqual(children.start.call_count, 2)
        first, second = children.start.call_args_list
        self.assertEqual(first.args[0], [str(self.python), '-X', 'utf8', '-B', '-m', 'backend.api', '--host', '127.0.0.1', '--port', '8891'])
        self.assertEqual(second.args[0][-1], 'backend.worker')
        self.assertIs(first.kwargs['env'], second.kwargs['env'])
        self.assertEqual(first.kwargs['cwd'], self.app)
        self.assertEqual(first.kwargs['env']['DATABASE_URL'], str(self.bundle / 'data' / 'teacher.sqlite'))
        browser.assert_not_called()
        children.close.assert_called_once()
        state = json.loads((self.bundle / 'data' / 'launcher.json').read_text(encoding='utf-8'))
        self.assertEqual(state['status'], 'stopped')
        self.assertEqual(state['url'], 'http://127.0.0.1:8891')

    def test_duplicate_launcher_does_not_spawn_or_stop_the_running_one(self):
        data = launcher.prepare_data(self.bundle)
        with exclusive_file_lock(data / 'launcher.lock'), \
             patch.object(launcher, 'Children') as children, patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(launcher.serve(self.app, self.bundle, self.python), 0)
        children.assert_not_called()
        self.assertIn('已经在运行', output.getvalue())

    def test_startup_crash_and_timeout_stop_owned_children_and_release_lock(self):
        for exit_code in (1, None):
            with self.subTest(exit_code=exit_code):
                children = self.fake_children(exit_code)
                with patch.object(launcher, 'Children', return_value=children), \
                     patch.object(launcher, 'available_port', return_value=8890), \
                     patch.object(launcher, 'ready', return_value=False), patch('sys.stdout', new_callable=io.StringIO):
                    with self.assertRaises(launcher.LaunchError):
                        launcher.serve(self.app, self.bundle, self.python, startup_timeout=0)
                children.close.assert_called_once()
                with exclusive_file_lock(self.bundle / 'data' / 'launcher.lock'):
                    pass

    def test_browser_failure_is_not_a_server_failure(self):
        children, stop = self.fake_children(), threading.Event()
        def health(*args):
            stop.set()
            return True
        with patch.object(launcher, 'Children', return_value=children), \
             patch.object(launcher, 'available_port', return_value=8890), \
             patch.object(launcher, 'ready', side_effect=health), \
             patch.object(launcher.webbrowser, 'open', side_effect=OSError('not installed')), \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(launcher.serve(self.app, self.bundle, self.python, stop=stop), 0)
        self.assertIn('复制上方网址', output.getvalue())

    def test_cmd_uses_bundled_python_and_quoted_paths(self):
        text = (ROOT / 'packaging/teacher/start.cmd').read_text(encoding='ascii')
        self.assertIn('DisableDelayedExpansion', text)
        self.assertIn('"%~dp0python\\python.exe" -I -X utf8 -B "%~dp0app\\scripts\\teacher_launcher.py"', text)
        self.assertNotIn('taskkill', text.lower())


@unittest.skipUnless(os.name == 'nt', 'Windows process container integration')
class PortableWindowsProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='teacher process ')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def wait_file(self, path, process=None):
        deadline = time.monotonic() + 10
        while not path.exists() and time.monotonic() < deadline:
            if process is not None and process.poll() is not None:
                self.fail(process.communicate()[1].decode('utf-8', errors='replace'))
            time.sleep(.05)
        self.assertTrue(path.exists(), 'fixture process did not start')
        return json.loads(path.read_text(encoding='utf-8'))

    def process_handle(self, pid):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE only
        self.assertTrue(handle)
        self.addCleanup(kernel.CloseHandle, handle)
        return kernel, handle

    def test_closing_job_kills_its_descendants_but_not_an_unrelated_process(self):
        marker = self.folder / 'owned.json'
        script = ('import json,os,subprocess,sys,time;from pathlib import Path;'
                  'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]);'
                  'Path(sys.argv[1]).write_text(json.dumps([os.getpid(),child.pid]),encoding="utf-8");time.sleep(60)')
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'])
        def cleanup_unrelated():
            if unrelated.poll() is None:unrelated.kill()
            unrelated.wait(timeout=5)
        self.addCleanup(cleanup_unrelated)
        group = launcher.Children()
        self.addCleanup(group.close)
        with (self.folder / 'owned.log').open('ab') as log:
            group.start([sys.executable, '-X', 'utf8', '-c', script, str(marker)],
                        cwd=ROOT, env=launcher.child_environment(self.folder, 8890), log=log)
            handles = [self.process_handle(pid) for pid in self.wait_file(marker)]
            group.close()
            for kernel, handle in handles:
                self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0)
        self.assertIsNone(unrelated.poll())

    def test_terminating_control_process_closes_job_without_a_finally_block(self):
        marker = self.folder / 'abrupt.json'
        inner = ('import os,json,sys,time;from pathlib import Path;'
                 'Path(sys.argv[1]).write_text(json.dumps([os.getpid()]),encoding="utf-8");time.sleep(60)')
        script = ('import sys,time;from scripts.teacher_launcher import Children,child_environment;from pathlib import Path;'
                  'group=Children();folder=Path(sys.argv[1]);log=(folder/"abrupt.log").open("ab");'
                  f'child=group.start([sys.executable,"-c",{inner!r},str(folder/"abrupt.json")],cwd=Path.cwd(),env=child_environment(folder,8890),log=log);time.sleep(60)')
        supervisor = subprocess.Popen([sys.executable, '-X', 'utf8', '-c', script, str(self.folder)], cwd=ROOT,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        def cleanup_supervisor():
            if supervisor.poll() is None:supervisor.kill()
            supervisor.communicate(timeout=5)
        self.addCleanup(cleanup_supervisor)
        handles = [self.process_handle(pid) for pid in self.wait_file(marker, supervisor)]
        supervisor.terminate()
        supervisor.communicate(timeout=5)
        for kernel, handle in handles:
            self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0)


if __name__ == '__main__':
    unittest.main()

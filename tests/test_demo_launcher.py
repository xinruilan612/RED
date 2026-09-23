"""Launcher boundaries and cleanup; real application smoke is an explicit CLI mode."""
import os
import io
from contextlib import closing, contextmanager
from http.cookiejar import CookieJar
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

from scripts import start_demo


@contextmanager
def live_demo_app(database, cookie_name):
    """Two actual loopback servers can share one browser-like, portless cookie jar."""
    import uvicorn
    from backend.api import create_app
    from backend.provider import Config
    from backend.store import Store
    with closing(socket.socket()) as listener:
        listener.bind(('127.0.0.1', 0))
        origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
        app = create_app(Store(database), Config(), origin=origin, invite='',
                         settings_override={}, session_cookie=cookie_name)
        server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise AssertionError('HTTP fixture failed to start')
                time.sleep(0.02)
            yield origin
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            if thread.is_alive():
                server.force_exit = True
                thread.join(timeout=5)
            if thread.is_alive():
                raise AssertionError('HTTP fixture did not stop')


class DemoLauncherTests(unittest.TestCase):
    def test_environment_is_scoped_no_paid_models_and_original_unchanged(self):
        original = dict(DATABASE_URL='postgresql://not-used', PUBLIC_ORIGIN='https://not-used.invalid',
                        DEEPSEEK_API_KEY='fixture-not-a-key', MODEL_ROUTES_JSON='invalid',
                        REGISTRATION_INVITE='not-used', KEEP_THIS='kept')
        snapshot = original.copy()
        with tempfile.TemporaryDirectory() as folder:
            env, database = start_demo.demo_environment(folder, 8786, original)
            self.assertEqual(database, Path(folder).resolve() / 'runtime/review-demo/demo.sqlite')
            self.assertEqual(env['DATABASE_URL'], str(database))
            self.assertFalse(database.parent.exists())
        self.assertEqual(original, snapshot)
        self.assertEqual(env['PUBLIC_ORIGIN'], 'http://127.0.0.1:8786')
        self.assertEqual(env['MODEL_ROUTES_JSON'], '{}')
        self.assertEqual(env['DEEPSEEK_API_KEY'], '')
        self.assertEqual(env['REGISTRATION_INVITE'], '')
        self.assertEqual(env['KEEP_THIS'], 'kept')

    def test_invalid_ports_and_redirected_storage_are_rejected(self):
        for port in (0, 80, 8765, 65536, True, '8786'):
            with self.subTest(port=port), self.assertRaises(ValueError):
                start_demo.demo_environment(start_demo.ROOT, port, {})
        with patch.object(Path, 'resolve', side_effect=[Path('/repo'), Path('/elsewhere/demo.sqlite')]):
            with self.assertRaisesRegex(ValueError, 'symlinks'):
                start_demo.demo_environment('/repo', 8786, {})

    def test_occupied_port_never_starts_process_or_creates_data(self):
        with socket.socket() as listener, tempfile.TemporaryDirectory() as folder:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            with patch.object(start_demo.subprocess, 'Popen') as spawn:
                with self.assertRaisesRegex(RuntimeError, 'no existing process was stopped'):
                    start_demo.run(listener.getsockname()[1], root=Path(folder))
                spawn.assert_not_called()
                self.assertFalse((Path(folder) / 'runtime').exists())
            self.assertGreater(listener.fileno(), -1)

    def test_partial_spawn_failure_cleans_started_child_and_log_handles(self):
        process = Mock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as folder, patch.object(start_demo, 'check_port'), \
                patch.object(start_demo.subprocess, 'Popen', side_effect=[process, OSError('fixture spawn failure')]) as spawn:
            with self.assertRaisesRegex(OSError, 'fixture spawn failure'):
                start_demo.run(root=Path(folder))
            process.terminate.assert_called_once()
            process.wait.assert_called_once()
            process.stdin.close.assert_called_once()
            for call in spawn.call_args_list:
                self.assertTrue(call.kwargs['stdout'].closed)
                self.assertEqual(call.kwargs['env']['DEEPSEEK_API_KEY'], '')
                if os.name == 'nt':
                    self.assertEqual(call.kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)

    def test_child_failure_stops_surviving_sibling(self):
        api, worker = Mock(), Mock()
        api.poll.return_value = 1
        worker.poll.return_value = None
        with tempfile.TemporaryDirectory() as folder, patch.object(start_demo, 'check_port'), \
                patch.object(start_demo.subprocess, 'Popen', side_effect=[api, worker]):
            with self.assertRaisesRegex(RuntimeError, 'api exited unexpectedly'):
                start_demo.run(root=Path(folder))
        api.terminate.assert_not_called()
        worker.terminate.assert_called_once()
        api.wait.assert_called_once()
        worker.wait.assert_called_once()

    def test_startup_timeout_cleans_both_children(self):
        children = [Mock(), Mock()]
        for process in children:
            process.poll.return_value = None
        with tempfile.TemporaryDirectory() as folder, patch.object(start_demo, 'check_port'), \
                patch.object(start_demo, 'ready', return_value=False), \
                patch.object(start_demo.subprocess, 'Popen', side_effect=children):
            with self.assertRaisesRegex(RuntimeError, 'Startup timed out'):
                start_demo.run(root=Path(folder), timeout=-1)
        for process in children:
            process.terminate.assert_called_once()
            process.wait.assert_called_once()

    def test_interrupt_cleans_both_children(self):
        children = [Mock(), Mock()]
        for process in children:
            process.poll.return_value = None
        with tempfile.TemporaryDirectory() as folder, patch.object(start_demo, 'check_port'), \
                patch.object(start_demo, 'ready', side_effect=KeyboardInterrupt), \
                patch.object(start_demo.subprocess, 'Popen', side_effect=children):
            with self.assertRaises(KeyboardInterrupt):
                start_demo.run(root=Path(folder))
        for process in children:
            process.terminate.assert_called_once()
            process.stdin.close.assert_called_once()

    def test_cleanup_escalates_only_its_own_unresponsive_child(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('fixture', 5), 0]
        start_demo.stop_children([('worker', process)])
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)
        process.stdin.close.assert_called_once()

    def test_cleanup_reaps_a_real_owned_process(self):
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                                   stdin=subprocess.PIPE, **options)
        try:
            start_demo.stop_children([('fixture', process)])
            self.assertIsNotNone(process.poll())
            self.assertTrue(process.stdin.closed)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    def test_ownership_pipe_eof_ends_a_real_child_without_parent_signal(self):
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        process = subprocess.Popen([sys.executable, '-c',
                                    'from scripts.start_demo import watch_parent; watch_parent()'],
                                   cwd=start_demo.ROOT, stdin=subprocess.PIPE, **options)
        try:
            self.assertIsNone(process.poll())
            process.stdin.close()
            self.assertEqual(process.wait(timeout=5), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    def test_ready_requires_this_workers_fresh_heartbeat(self):
        opener = Mock()
        opener.open.side_effect = lambda *_args, **_kwargs: io.BytesIO(b'{"status":"ok","database":"sqlite"}')
        with tempfile.TemporaryDirectory() as folder, patch.object(start_demo, 'build_opener', return_value=opener):
            database = Path(folder) / 'demo.sqlite'
            with closing(sqlite3.connect(database)) as db:
                db.execute('CREATE TABLE runtime_workers (id TEXT, heartbeat REAL)')
                db.execute('INSERT INTO runtime_workers VALUES (?, ?)', ('other', time.time()))
                db.commit()
                self.assertFalse(start_demo.ready('http://127.0.0.1:8786', database, 'mine'))
                db.execute('INSERT INTO runtime_workers VALUES (?, ?)', ('mine', time.time() - 30))
                db.commit()
                self.assertFalse(start_demo.ready('http://127.0.0.1:8786', database, 'mine'))
                db.execute('UPDATE runtime_workers SET heartbeat=? WHERE id=?', (time.time(), 'mine'))
                db.commit()
                self.assertTrue(start_demo.ready('http://127.0.0.1:8786', database, 'mine'))

    def test_check_mode_does_not_start_or_create_database(self):
        with patch.object(start_demo, 'dependencies') as dependencies, patch.object(start_demo, 'run') as run:
            self.assertEqual(start_demo.main(['--check']), 0)
            dependencies.assert_called_once()
            run.assert_not_called()

    def test_child_mode_rejects_non_demo_database_before_importing_backend(self):
        with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://not-used'}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'isolated demo environment'):
                start_demo.child('worker', 8786)

    def test_explicit_api_settings_do_not_read_author_dotenv(self):
        from backend.api import create_app
        from backend.provider import Config
        from backend.store import Store
        with tempfile.TemporaryDirectory() as folder, patch('backend.api.settings', side_effect=AssertionError('dotenv read')):
            app = create_app(Store(Path(folder) / 'demo.sqlite'), Config(),
                             settings_override={'PUBLIC_ORIGIN': 'http://127.0.0.1:8786', 'REGISTRATION_INVITE': ''})
            self.assertFalse(app.state.service.config.ready)

    def test_invalid_session_cookie_names_are_rejected_before_database_access(self):
        from backend.api import create_app
        from backend.contracts import DomainError
        for name in ('', 'bad;name', 'bad=name', 'bad name', 'bad\r\nname', '中文', 'a' * 65, None):
            with self.subTest(name=name), patch('backend.api.Store') as store:
                with self.assertRaises(DomainError):
                    create_app(settings_override={}, session_cookie=name)
                store.assert_not_called()

    def test_launcher_selects_demo_cookie_namespace(self):
        env, _ = start_demo.demo_environment(start_demo.ROOT, 8786, {})
        with patch.dict(os.environ, env, clear=True), patch.object(start_demo.threading, 'Thread'), \
                patch('backend.store.Store'), patch('backend.api.create_app') as create, \
                patch('uvicorn.run'):
            start_demo.child('api', 8786)
        self.assertEqual(create.call_args.kwargs['session_cookie'], 'youji_review_session')
        self.assertFalse(create.call_args.args[1].ready)
        self.assertEqual(create.call_args.kwargs['settings_override'], env)

    def test_real_http_default_and_demo_sessions_csrf_and_logout_are_isolated(self):
        jar = CookieJar()
        opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(jar))

        def request(origin, path, data=None, csrf=''):
            headers = {'Origin': origin, 'X-CSRF-Token': csrf, 'Content-Type': 'application/json'}
            body = None if data is None else json.dumps(data).encode('utf-8')
            with opener.open(Request(origin + path, data=body, headers=headers), timeout=5) as response:
                return json.load(response)

        def cookie(name):
            return next((entry.value for entry in jar if entry.name == name), None)

        with tempfile.TemporaryDirectory() as folder, \
                live_demo_app(Path(folder) / 'main.sqlite', 'youji_session') as main, \
                live_demo_app(Path(folder) / 'review.sqlite', 'youji_review_session') as review:
            main_csrf = request(main, '/api/session')['csrf']
            main_auth = request(main, '/api/auth/register',
                                {'username': 'mainjudge', 'password': 'FixturePassword'}, main_csrf)
            main_token = cookie('youji_session')
            review_csrf = request(review, '/api/session')['csrf']
            self.assertEqual(cookie('youji_session'), main_token)
            review_auth = request(review, '/api/auth/register',
                                  {'username': 'reviewjudge', 'password': 'FixturePassword'}, review_csrf)
            self.assertEqual({entry.name for entry in jar}, {'youji_session', 'youji_review_session'})
            self.assertEqual(request(main, '/api/session')['user']['username'], 'mainjudge')
            self.assertEqual(request(review, '/api/session')['user']['username'], 'reviewjudge')
            self.assertIn('accounts', request(main, '/api/operations'))
            self.assertIn('accounts', request(review, '/api/operations'))
            with self.assertRaises(HTTPError) as mismatch:
                request(review, '/api/auth/logout', {}, main_auth['csrf'])
            self.assertEqual(mismatch.exception.code, 403)
            mismatch.exception.close()
            self.assertTrue(request(review, '/api/auth/logout', {}, review_auth['csrf'])['ok'])
            self.assertIsNone(cookie('youji_review_session'))
            self.assertEqual(cookie('youji_session'), main_token)
            self.assertEqual(request(main, '/api/session')['user']['username'], 'mainjudge')
            self.assertIsNone(request(review, '/api/session')['user'])
            fresh_demo_token = cookie('youji_review_session')
            self.assertTrue(request(main, '/api/auth/logout', {}, main_auth['csrf'])['ok'])
            self.assertIsNone(cookie('youji_session'))
            self.assertEqual(cookie('youji_review_session'), fresh_demo_token)


if __name__ == '__main__':
    unittest.main()

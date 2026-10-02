"""CI isolation contract tests; never start PostgreSQL or call external models."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import ci_postgres as ci


class CIIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'checkout'
        self.runner_temp = self.base / 'runner-temp'
        self.root.mkdir()
        self.runner_temp.mkdir()
        self.env = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
                    'GITHUB_WORKSPACE': str(self.root), 'RUNNER_TEMP': str(self.runner_temp)}

    def cluster(self):
        return ci.TemporaryPostgres(self.runner_temp, {name: name for name in ci.BINARIES}, {})

    def started_cluster(self, cluster):
        cluster.data.mkdir()
        (cluster.data / 'postgresql.conf').write_text('# initial\n', encoding='utf-8')
        (cluster.data / 'postmaster.pid').write_text(f'99999\n{cluster.data.resolve()}\n0\n{cluster.port}\n', encoding='utf-8')

    def test_hosted_ci_with_separate_temporary_directory_is_required(self):
        self.assertEqual(ci.ci_context(self.env, self.root), self.runner_temp.resolve())
        for changed in ({'GITHUB_ACTIONS': 'false'}, {'RUNNER_ENVIRONMENT': 'self-hosted'},
                        {'GITHUB_WORKSPACE': str(self.runner_temp)}, {'RUNNER_TEMP': ''},
                        {'RUNNER_TEMP': str(self.root)}, {'RUNNER_TEMP': str(self.base)},
                        {'RUNNER_TEMP': str(Path(self.runner_temp.anchor))}):
            with self.subTest(changed=changed), self.assertRaises(RuntimeError):
                ci.ci_context({**self.env, **changed}, self.root)

    def test_workspace_child_is_not_an_allowed_cluster_base(self):
        child = self.root / 'runtime'
        child.mkdir()
        with self.assertRaises(RuntimeError):
            ci.ci_context({**self.env, 'RUNNER_TEMP': str(child)}, self.root)

    def test_dotenv_is_never_read_or_allowed_in_ci(self):
        (self.root / '.env').write_text('DUMMY_NOT_A_CREDENTIAL=yes', encoding='utf-8')
        with patch.object(Path, 'read_text', side_effect=AssertionError('must not read dotenv')), self.assertRaises(RuntimeError):
            ci.ci_context(self.env, self.root)

    def test_inherited_connections_and_credentials_are_removed(self):
        original = {**self.env, 'PATH': '/tools', 'PGDATA': '/existing', 'PGHOST': 'external',
                    'PGPORT': '5432', 'PGSERVICE': 'business', 'PGPASSWORD': 'dummy',
                    'PGOPTIONS': '-c search_path=business', 'DATABASE_URL': 'not-used',
                    'TEST_DATABASE_URL': 'not-used', 'FIXTURE_DATABASE_URL': 'not-used',
                    'OPENAI_API_KEY': 'dummy', 'DEEPSEEK_API_KEY': 'dummy',
                    'LANGSMITH_API_KEY': 'dummy', 'MODEL_ROUTES_JSON': '{}',
                    'ACTIONS_RUNTIME_TOKEN': 'dummy'}
        safe = ci.test_environment(original)
        self.assertFalse(any(key.startswith('PG') for key in safe))
        self.assertNotIn('DATABASE_URL', safe)
        self.assertNotIn('OPENAI_API_KEY', safe)
        self.assertNotIn('LANGSMITH_API_KEY', safe)
        self.assertNotIn('ACTIONS_RUNTIME_TOKEN', safe)
        self.assertEqual(safe['DEEPSEEK_API_KEY'], '')
        self.assertEqual(safe['PATH'], '/tools')
        self.assertEqual(safe['PYTHONIOENCODING'], 'utf-8')
        self.assertEqual(safe['LANGSMITH_TRACING'], 'false')
        self.assertEqual(original['DEEPSEEK_API_KEY'], 'dummy')

    def test_dry_run_never_executes_a_process_or_creates_cluster(self):
        output = io.StringIO()
        with patch('sys.stdout', output), patch.object(ci, 'command', side_effect=AssertionError('process forbidden')), patch.object(ci, 'TemporaryPostgres', side_effect=AssertionError('cluster forbidden')):
            self.assertEqual(ci.main(['--dry-run']), 0)
        plan = json.loads(output.getvalue())
        self.assertFalse(plan['database_started'])
        self.assertFalse(plan['allow_skips'])
        self.assertEqual((plan['node_test_files'], plan['js_syntax_files']), (5, 9))

    def test_normal_execution_refuses_local_environment_before_running_commands(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(ci, 'command', side_effect=AssertionError('process forbidden')), patch('sys.stderr', io.StringIO()):
            self.assertEqual(ci.main([]), 1)

    def test_new_cluster_has_unique_direct_child_and_ownership_marker(self):
        first, second = self.cluster(), self.cluster()
        self.assertNotEqual(first.path, second.path)
        first.validate_owned()
        self.assertEqual(first.path.parent, self.runner_temp.resolve())
        self.assertEqual(first.path.name[:10], 'red-ci-pg-')
        self.assertEqual((first.path / '.red-ci-owned').read_text(encoding='utf-8'), first.marker)
        first.close()
        second.close()

    def test_changed_marker_blocks_start_stop_and_recursive_cleanup(self):
        cluster = self.cluster()
        (cluster.path / '.red-ci-owned').write_text('changed', encoding='utf-8')
        with patch.object(ci, 'command', side_effect=AssertionError('must not touch processes')), patch.object(ci.shutil, 'rmtree', side_effect=AssertionError('must not remove')):
            with self.assertRaises(RuntimeError):
                cluster.pg('pg_ctl', 'stop')
            with self.assertRaises(RuntimeError):
                cluster.close()
        self.assertTrue(cluster.path.is_dir())

    def test_cluster_escape_blocks_cleanup(self):
        cluster = self.cluster()
        cluster.path = self.root
        with patch.object(ci.shutil, 'rmtree', side_effect=AssertionError('must not remove')), self.assertRaises(RuntimeError):
            cluster.close()
        self.assertTrue(self.root.exists())

    def test_cleanup_only_stops_owned_data_directory_not_a_service(self):
        cluster = self.cluster()
        self.started_cluster(cluster)
        cluster.attempted_start = True
        def stopped(*args, **kwargs):
            (cluster.data / 'postmaster.pid').unlink()
            return Mock(stdout='')
        with patch.object(ci, 'command', side_effect=stopped) as run:
            cluster.close()
        self.assertEqual(run.call_args.args[0], ['pg_ctl', '-D', cluster.data, '-w', '-t', '30', '-m', 'fast', 'stop'])
        self.assertFalse(cluster.path.exists())

    def test_changed_pid_identity_is_never_stopped_or_deleted(self):
        cluster = self.cluster()
        self.started_cluster(cluster)
        cluster.attempted_start = True
        (cluster.data / 'postmaster.pid').write_text(f'99999\n{self.root}\n0\n{cluster.port}\n', encoding='utf-8')
        with patch.object(ci, 'command', side_effect=AssertionError('must not stop unknown process')), patch.object(ci.shutil, 'rmtree', side_effect=AssertionError('must not remove')), self.assertRaises(RuntimeError):
            cluster.close()

    def test_unconfirmed_stop_preserves_temporary_data(self):
        cluster = self.cluster()
        self.started_cluster(cluster)
        cluster.attempted_start = True
        with patch.object(ci, 'command', return_value=Mock()), patch.object(ci.shutil, 'rmtree', side_effect=AssertionError('must not remove')), self.assertRaisesRegex(RuntimeError, 'not confirmed'):
            cluster.close()
        self.assertTrue(cluster.data.is_dir())

    def test_start_checks_identity_before_creating_test_database(self):
        cluster = self.cluster()
        self.started_cluster(cluster)
        identity = f'{cluster.data.resolve()}\n127.0.0.1\n{cluster.port}\n'
        with patch.object(ci, 'command', return_value=Mock(stdout=identity)) as run:
            url = cluster.start()
        calls = [call.args[0] for call in run.call_args_list]
        self.assertEqual([args[0] for args in calls], ['initdb', 'pg_ctl', 'psql', 'createdb'])
        self.assertIn('--encoding=UTF8', calls[0])
        self.assertEqual(url, f'postgresql://red_ci@127.0.0.1:{cluster.port}/red_ci_test')
        self.assertEqual(calls[-1][1:], ['-h', '127.0.0.1', '-p', str(cluster.port), '-U', 'red_ci', '--encoding=UTF8', 'red_ci_test'])
        config = (cluster.data / 'postgresql.conf').read_text(encoding='utf-8')
        self.assertIn("listen_addresses = '127.0.0.1'", config)
        self.assertIn("unix_socket_directories = ''", config)

    def test_wrong_server_identity_never_creates_database(self):
        cluster = self.cluster()
        self.started_cluster(cluster)
        with patch.object(ci, 'command', return_value=Mock(stdout=f'{self.root}\n127.0.0.1\n{cluster.port}\n')) as run:
            with self.assertRaisesRegex(RuntimeError, 'unverified server'):
                cluster.start()
        self.assertNotIn('createdb', [call.args[0][0] for call in run.call_args_list])

    def test_wrong_pid_directory_never_connects_or_creates_database(self):
        cluster = self.cluster()
        self.started_cluster(cluster)
        (cluster.data / 'postmaster.pid').write_text(f'99999\n{self.root}\n0\n{cluster.port}\n', encoding='utf-8')
        with patch.object(ci, 'command', return_value=Mock(stdout='')) as run:
            with self.assertRaisesRegex(RuntimeError, 'identity'):
                cluster.start()
        self.assertEqual([call.args[0][0] for call in run.call_args_list], ['initdb', 'pg_ctl'])

    def test_binary_version_mismatch_has_no_service_fallback(self):
        folder = self.base / 'binaries'
        folder.mkdir()
        for name in ci.BINARIES:
            (folder / (name + ('.exe' if os.name == 'nt' else ''))).touch()
        with patch.object(ci, 'command', return_value=Mock(stdout='tool (PostgreSQL) 15.1')) as run:
            with self.assertRaisesRegex(RuntimeError, 'selected major'):
                ci.postgres_binaries({'RED_CI_PG_BIN': str(folder)}, 17)
        self.assertEqual(run.call_count, len(ci.BINARIES))
        with self.assertRaises(RuntimeError):
            ci.postgres_binaries({}, 18)

    def test_python_gate_rejects_skips_and_empty_discovery(self):
        for count, skipped, successful in ((1, [('case', 'reason')], True), (0, [], True), (1, [], False)):
            result = Mock(testsRun=count, skipped=skipped, failures=[], errors=[])
            result.wasSuccessful.return_value = successful
            with self.subTest(count=count, skipped=skipped, successful=successful), patch.object(ci.unittest.defaultTestLoader, 'discover', return_value='suite'), patch.object(ci.unittest, 'TextTestRunner') as runner:
                runner.return_value.run.return_value = result
                with self.assertRaises(RuntimeError):
                    ci.run_python_tests()

    def test_python_gate_accepts_only_actual_nonempty_zero_skip_success(self):
        result = Mock(testsRun=12, skipped=[], failures=[], errors=[])
        result.wasSuccessful.return_value = True
        with patch.object(ci.unittest.defaultTestLoader, 'discover', return_value='suite'), patch.object(ci.unittest, 'TextTestRunner') as runner:
            runner.return_value.run.return_value = result
            self.assertEqual(ci.run_python_tests(), 12)

    def test_parent_environment_is_restored_even_on_failure(self):
        before = dict(os.environ)
        with self.assertRaises(RuntimeError):
            with ci.replaced_environment({'ONLY': 'test'}):
                self.assertEqual(dict(os.environ), {'ONLY': 'test'})
                raise RuntimeError('fixture')
        self.assertEqual(dict(os.environ), before)

    def test_all_declared_frontend_gates_and_launcher_help_are_executed(self):
        with patch.object(ci, 'check_utf8', return_value=40), patch.object(ci, 'run_python_tests', return_value=12), patch.object(ci, 'command', return_value=Mock()) as run:
            report = ci.run_gates({})
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0], [ci.sys.executable, '-m', 'pip', 'check'])
        self.assertEqual(commands[1], ['git', 'diff', '--check'])
        self.assertEqual(commands[2], ['node', '--test', *[f'tests/{name}.test.js' for name in ci.NODE_TESTS]])
        self.assertEqual(len(commands[3:-1]), 9)
        self.assertEqual(commands[-1][1:], ['scripts/local_dev.py', '--help'])
        self.assertEqual((report['python_tests'], report['python_skipped']), (12, 0))
        self.assertEqual((report['dependency_check'], report['whitespace_check']), ('passed', 'passed'))

    def test_startup_failure_still_closes_only_the_new_cluster(self):
        cluster = Mock()
        cluster.start.side_effect = RuntimeError('fixture startup failure')
        with patch.object(ci, 'ci_context', return_value=self.runner_temp), patch.object(ci.sys, 'version_info', (3, 12, 10)), patch.object(ci, 'postgres_binaries', return_value=({}, 'PostgreSQL 17.11')), patch.object(ci, 'command', return_value=Mock(stdout='v22.23.2')), patch.object(ci, 'TemporaryPostgres', return_value=cluster), patch.object(ci, 'run_gates', side_effect=AssertionError('must not run')), patch('sys.stderr', io.StringIO()), patch.dict(os.environ, {'RED_CI_PG_MAJOR': '17'}, clear=True):
            self.assertEqual(ci.main([]), 1)
        cluster.close.assert_called_once_with()

    def test_wrong_python_or_node_version_prevents_cluster_creation(self):
        for python, node in (((3, 11, 0), 'v22.0.0'), ((3, 12, 10), 'v24.0.0')):
            with self.subTest(python=python, node=node), patch.object(ci, 'ci_context', return_value=self.runner_temp), patch.object(ci.sys, 'version_info', python), patch.object(ci, 'postgres_binaries', return_value=({}, 'PostgreSQL 17.11')), patch.object(ci, 'command', return_value=Mock(stdout=node)), patch.object(ci, 'TemporaryPostgres', side_effect=AssertionError('must not create cluster')), patch('sys.stderr', io.StringIO()), patch.dict(os.environ, {'RED_CI_PG_MAJOR': '17'}, clear=True):
                self.assertEqual(ci.main([]), 1)

    def test_workflow_has_four_architectures_pinned_actions_and_no_credentials(self):
        import yaml
        workflow = yaml.safe_load((ci.ROOT / '.github/workflows/cross-platform.yml').read_text(encoding='utf-8'))
        job = workflow['jobs']['acceptance']
        labels = {row['os']: row['architecture'] for row in job['strategy']['matrix']['include']}
        self.assertEqual(labels, {'windows-2025': 'x64', 'macos-15': 'arm64', 'macos-15-intel': 'x64', 'ubuntu-24.04': 'x64'})
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        self.assertNotIn('services', job)
        steps = job['steps']
        self.assertEqual([step['uses'] for step in steps if 'uses' in step], [
            'actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09',
            'actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1',
            'actions/setup-node@a0853c24544627f65ddf259abe73b1d18a591444'])
        self.assertFalse(steps[0]['with']['persist-credentials'])
        self.assertNotIn('secrets.', json.dumps(workflow))
        self.assertEqual(steps[-1]['run'], 'python scripts/ci_postgres.py')


if __name__ == '__main__':
    unittest.main()

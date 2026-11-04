import io
import time
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch
from scripts import deploy_check


class DeploymentCheckTests(unittest.TestCase):
    def env(self):
        return {'PUBLIC_ORIGIN': 'https://youji.example.org',
                'DATABASE_URL': 'postgresql://youji:private@localhost/youji',
                'REGISTRATION_INVITE': 'private-invite-123456', 'DEEPSEEK_API_KEY': ''}

    def test_simulated_acceptance_needs_no_model_key(self):
        self.assertEqual(deploy_check.validate(self.env()), [])

    def test_rejects_unsafe_or_incomplete_public_configuration(self):
        cases = {'PUBLIC_ORIGIN': ['http://youji.example.org', 'https://localhost',
                                  'https://youji.example.org/path', 'https://user:private@youji.example.org',
                                  'https://youji.example.org:bad', 'https://CHANGE_ME.example.com'],
                 'DATABASE_URL': ['runtime/demo.sqlite', 'postgresql:///','postgresql://youji:CHANGE_ME@localhost/youji'],
                 'REGISTRATION_INVITE': ['short', 'CHANGE_ME_CHANGE_ME', 'a long invite with spaces'],
                 'DEEPSEEK_API_KEY': ['private key'], 'WINDTUNNEL_ALLOW_LIVE': ['true']}
        for name, values in cases.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    self.assertTrue(deploy_check.validate({**self.env(), name: value}))

    def test_diagnostics_never_print_secrets_or_raw_errors(self):
        with patch('backend.api.settings', return_value=self.env()), patch('backend.provider.load_config'), \
             patch.object(deploy_check, 'check_database', side_effect=RuntimeError('SECRET_DATABASE_PASSWORD_123')), \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(deploy_check.main(['--database']), 1)
        self.assertNotIn('SECRET_DATABASE_PASSWORD_123', output.getvalue())
        self.assertNotIn(self.env()['DATABASE_URL'], output.getvalue())

    def test_default_check_does_not_connect_to_database(self):
        with patch('backend.api.settings', return_value=self.env()), patch('backend.provider.load_config'), \
             patch.object(deploy_check, 'check_database') as check, patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(deploy_check.main([]), 0)
            check.assert_not_called()

    def test_read_only_role_and_worker_checks(self):
        db = Mock()
        @contextmanager
        def connection(target):
            yield db
        for role, heartbeat, success in [((False, False, False), time.time(), True),
                                         ((True, False, False), time.time(), False),
                                         ((False, True, False), time.time(), False),
                                         ((False, False, False), None, False),
                                         ((False, False, False), time.time()-100, False)]:
            with self.subTest(role=role, heartbeat=heartbeat), patch('backend.database.connect', connection):
                db.execute.return_value.fetchone.side_effect = [role, (heartbeat,)]
                if success:
                    deploy_check.check_database(self.env()['DATABASE_URL'], worker=True)
                else:
                    with self.assertRaises(RuntimeError):
                        deploy_check.check_database(self.env()['DATABASE_URL'], worker=True)
                self.assertEqual(db.execute.call_args_list[0].args[0], 'SET TRANSACTION READ ONLY')
                db.reset_mock()

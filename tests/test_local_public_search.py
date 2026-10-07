import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from scripts import local_public_search, local_dev


class PublicLauncherTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.folder = self.root / 'runtime' / 'xhs'
        self.folder.mkdir(parents=True)
        self.binary = self.folder / ('xiaohongshu-mcp.exe' if os.name == 'nt' else 'xiaohongshu-mcp')
        self.binary.touch()
        (self.folder / 'auth-token').write_text('test-secret')

    def test_missing_token_skips_without_network(self):
        (self.folder / 'auth-token').unlink()
        with patch.object(local_public_search, 'healthy') as health, patch.object(local_public_search.subprocess, 'Popen') as launch:
            self.assertIsNone(local_public_search.start_optional(self.root))
        health.assert_not_called()
        launch.assert_not_called()

    def test_healthy_existing_service_not_owned(self):
        with patch.object(local_public_search, 'healthy', return_value=True), patch.object(local_public_search.subprocess, 'Popen') as launch:
            self.assertIsNone(local_public_search.start_optional(self.root))
        launch.assert_not_called()

    def test_occupied_unhealthy_port_not_touched(self):
        with patch.object(local_public_search, 'healthy', return_value=False), patch.object(local_public_search.socket, 'socket') as sock, patch.object(local_public_search.subprocess, 'Popen') as launch:
            sock.return_value.__enter__.return_value.bind.side_effect = OSError()
            self.assertIsNone(local_public_search.start_optional(self.root))
        launch.assert_not_called()

    def test_token_env_local_bind_absolute_cookie_path(self):
        with patch.object(local_public_search, 'healthy', return_value=False), patch.object(local_public_search.socket, 'socket'), patch.object(local_public_search.subprocess, 'Popen') as launch:
            child = local_public_search.start_optional(self.root)
        self.assertIs(child, launch.return_value)
        args, kwargs = launch.call_args
        self.assertNotIn('test-secret', str(args))
        self.assertIn('127.0.0.1:18060', args[0])
        self.assertEqual(kwargs['env']['AUTH_TOKEN'], 'test-secret')
        self.assertEqual(kwargs['env']['COOKIES_PATH'], str((self.folder / 'cookies.json').resolve()))
        self.assertEqual(kwargs['stdout'], local_public_search.subprocess.DEVNULL)

    def test_optional_start_failure_nonfatal(self):
        with patch.object(local_public_search, 'healthy', return_value=False), patch.object(local_public_search.socket, 'socket'), patch.object(local_public_search.subprocess, 'Popen', side_effect=OSError()):
            self.assertIsNone(local_public_search.start_optional(self.root))

    def test_launcher_stops_only_owned_connector(self):
        api, worker, connector = Mock(), Mock(), Mock()
        for child in (api, worker, connector):
            child.poll.return_value = None
        with patch.object(local_dev.socket, 'socket'), patch.object(local_dev.subprocess, 'Popen', side_effect=[api, worker]), patch('scripts.local_public_search.start_optional', return_value=connector), patch.object(local_dev.time, 'sleep', side_effect=KeyboardInterrupt):
            local_dev.serve({})
        connector.terminate.assert_called_once()
        connector.wait.assert_called_once()

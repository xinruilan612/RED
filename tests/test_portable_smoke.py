"""Driver contract tests, separate from acceptance of a real packaged executable."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from scripts import portable_smoke as smoke, portable_launcher as launcher
from backend.knowledge import parse_file

class PortableSmokeTests(unittest.TestCase):
    def test_stdlib_file_fixtures_reach_real_parsers(self):
        pdf=parse_file('offline.pdf',smoke.pdf_fixture())
        self.assertIn('Offline portable PDF evidence.',pdf[0][1])
        doc=parse_file('offline.docx',smoke.docx_fixture())
        self.assertIn('中文离线资料',doc[0][1])
    def test_command_uses_actual_executable_without_python_or_shell(self):
        self.assertEqual(smoke.command(Path('/installed/Youji'),['--check']),['/installed/Youji','--check'])
    def test_driver_has_no_application_imports_and_no_paid_endpoints(self):
        import ast
        tree=ast.parse(Path(smoke.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):self.assertFalse((node.module or '').startswith(('backend','scripts')))
        source=Path(smoke.__file__).read_text()
        for endpoint in ('/api/runs','/api/operations/agent-plan','/api/operations/ai-review','/api/sources'):
            self.assertNotIn(endpoint,source)
        self.assertIn('deepseek_api_key":""',source)
    def test_fixture_media_service_dispatch_is_explicit(self):
        with patch.object(launcher,'offline_self_test') as execute:
            result=launcher.main(['--service','self-test','--self-test-output','/tmp/offline-only'])
            self.assertEqual(result,0);execute.assert_called_once_with('/tmp/offline-only')
        with patch.object(launcher,'offline_self_test') as execute:
            self.assertEqual(launcher.main(['--service','self-test']),1);execute.assert_not_called()

if __name__=='__main__':unittest.main()

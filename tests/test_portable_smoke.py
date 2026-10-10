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
    def test_http_failure_has_safe_path_and_reason_not_credentials(self):
        import urllib.error
        http=smoke.HTTP('http://127.0.0.1:12345')
        failure=urllib.error.URLError(ConnectionRefusedError(10061,'secret-cookie private-key'))
        with patch.object(http.opener,'open',side_effect=failure):
            with self.assertRaises(smoke.HTTPFailure) as caught:
                http.request('/api/knowledge?account_id=private-key',{'password':'secret-cookie'})
        diagnostic=caught.exception.diagnostic
        self.assertEqual(diagnostic['path'],'/api/knowledge')
        self.assertEqual(diagnostic['method'],'POST')
        self.assertEqual(diagnostic['errno'],10061)
        self.assertNotIn('private-key',str(caught.exception))
        self.assertNotIn('secret-cookie',json.dumps(diagnostic))
    def test_readiness_failure_cannot_pass_smoke(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            ready=Path(folder)/'ready.json';process=Mock();process.poll.return_value=1
            with patch.object(smoke.subprocess,'Popen',return_value=process),patch.object(smoke,'stop') as stop:
                with self.assertRaisesRegex(RuntimeError,'did not become ready'):
                    smoke.start(Path('/installed/app'),Path(folder),Path(folder)/'config',ready,io.StringIO())
                stop.assert_called_once_with(process)

    def test_offline_failure_preserves_redacted_exception_chain(self):
        import os
        def fail(*_):
            try:raise OSError('Chromium missing DLL synthetic-private-key')
            except OSError as error:raise RuntimeError('media unavailable') from error
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'DEEPSEEK_API_KEY':'synthetic-private-key'}),patch.object(launcher,'offline_self_test',side_effect=fail):
            self.assertEqual(launcher.main(['--service','self-test','--self-test-output',folder]),1)
            root=Path(folder);log=(root/'self-test-error.log').read_text()
            self.assertIn('Chromium missing DLL',log);self.assertIn('RuntimeError',log)
            self.assertNotIn('synthetic-private-key',log)
            packet=json.loads((root/'self-test-error.json').read_text())
            self.assertEqual(packet['error_chain'],['RuntimeError','OSError'])
            self.assertEqual(packet['paid_model_calls'],0)
    def test_media_driver_uses_synthetic_directory_and_keeps_failure_log(self):
        import os
        def execute(argv,**kwargs):
            self.assertIn('--data-dir',argv)
            self.assertEqual(kwargs['env']['DEEPSEEK_API_KEY'],'')
            self.assertNotIn('SOME_SECRET_TOKEN',kwargs['env'])
            media=Path(argv[argv.index('--self-test-output')+1]);media.mkdir()
            (media/'self-test-error.log').write_text('synthetic Chromium DLL error')
            (media/'self-test-error.json').write_text('{"error_chain":["DomainError","Error"]}')
            return subprocess.CompletedProcess(argv,1,b'chromium step\n',b'self-test failed\n')
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'SOME_SECRET_TOKEN':'never-pass'}),patch.object(smoke.subprocess,'run',side_effect=execute):
            root=Path(folder);output=root/'output';output.mkdir()
            with self.assertRaises(smoke.MediaFailure) as caught:
                smoke.run_media(Path('/installed/app'),root,output/'media',output)
            self.assertEqual(caught.exception.diagnostic['stage'],'offline_media')
            self.assertEqual(caught.exception.diagnostic['error_chain'],['DomainError','Error'])
            self.assertIn('synthetic Chromium DLL error',(output/'offline-media-smoke.log').read_text())

    def test_fixture_media_service_dispatch_is_explicit(self):
        with patch.object(launcher,'offline_self_test') as execute:
            result=launcher.main(['--service','self-test','--self-test-output','/tmp/offline-only'])
            self.assertEqual(result,0);execute.assert_called_once_with('/tmp/offline-only')
        with patch.object(launcher,'offline_self_test') as execute:
            self.assertEqual(launcher.main(['--service','self-test']),1);execute.assert_not_called()

if __name__=='__main__':unittest.main()

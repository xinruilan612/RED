import unittest
from unittest.mock import patch, Mock
from scripts.xhs_sync import main

class XHSLauncherTests(unittest.TestCase):
    def test_worker_dispatch_keeps_creation_and_research_scheduler(self):
        store=Mock()
        with patch('sys.argv',['xhs_sync.py','worker','--schema','isolated_test']), \
             patch('scripts.xhs_sync.settings',return_value={'DATABASE_URL':'postgresql://localhost/test'}), \
             patch('scripts.xhs_sync.Store',return_value=store) as constructor, \
             patch('scripts.xhs_sync.upgrade'), patch('backend.service.Service') as service, \
             patch('backend.worker.Worker') as worker, patch('backend.provider.load_config',return_value=None):
            main()
        self.assertIn('search_path%3Disolated_test',constructor.call_args.args[0])
        service.assert_called_once_with(store,None)
        worker.return_value.run.assert_called_once_with()

    def test_bridge_is_headless_and_reuses_project_cookie_file(self):
        with patch('sys.argv',['xhs_sync.py','bridge']), \
             patch('scripts.xhs_sync.Path.read_text',return_value='test-control'), \
             patch('scripts.xhs_sync.os.chdir'), patch('scripts.xhs_sync.os.umask'), \
             patch('scripts.xhs_sync.os.execv',side_effect=SystemExit) as run, \
             patch.dict('os.environ',{},clear=True):
            import os
            with self.assertRaises(SystemExit):main()
            self.assertIn('-headless=true',run.call_args.args[1])
            self.assertNotIn('-headless=false',run.call_args.args[1])
            from pathlib import Path
            self.assertEqual(Path(os.environ['COOKIES_PATH']).parts[-4:],('runtime','xhs-local','session','cookies.json'))
            self.assertEqual(os.environ['AUTH_TOKEN'],'test-control')
            self.assertNotIn('test-control',str(run.call_args.args))

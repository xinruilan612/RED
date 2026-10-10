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

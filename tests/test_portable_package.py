import json
from pathlib import Path
import tempfile
import unittest
from scripts.provision_portable import provision


class ProvisionTests(unittest.TestCase):
    def test_only_explicit_credential_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'Youji').touch(); (root/'build-manifest.json').write_text('{}')
            target=provision(root,'synthetic-test-key')
            self.assertEqual(json.loads(target.read_text()),{'schema_version':1,'deepseek_api_key':'synthetic-test-key','windtunnel_allow_live':True})
            with self.assertRaises(FileExistsError): provision(root,'different-test-key')
            self.assertIn('synthetic-test-key',target.read_text())

    def test_unbuilt_and_invalid_keys_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with self.assertRaises(ValueError): provision(root,'synthetic')
            (root/'Youji').touch(); (root/'build-manifest.json').write_text('{}')
            for key in ['', 'bad\nkey', None]:
                with self.assertRaises(ValueError): provision(root,key)
            self.assertFalse((root/'provision.json').exists())


class PackagedBrowserTests(unittest.TestCase):
    def test_packaged_browser_precedes_system_chrome(self):
        from unittest.mock import patch
        from backend.html_cards import browser_arguments
        with patch.dict('os.environ', {'PLAYWRIGHT_BROWSERS_PATH':'/packaged/browser'}, clear=True), patch('pathlib.Path.is_file', return_value=True):
            self.assertEqual(browser_arguments(), {})
        with patch.dict('os.environ', {'YOUJI_CHROMIUM_EXECUTABLE':'/custom/chrome'}, clear=True):
            self.assertEqual(browser_arguments(), {'executable_path':'/custom/chrome'})

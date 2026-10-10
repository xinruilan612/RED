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
            self.assertTrue(json.loads((root/'private-distribution.json').read_text())['credential_included'])
            self.assertNotIn('synthetic-test-key',(root/'使用说明.txt').read_text())

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


class NativeEvidenceTests(unittest.TestCase):
    def test_ci_retains_only_explicit_synthetic_reports_for_acceptance(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/portable-package.yml').read_text()
        evidence = workflow.split('name: Preserve synthetic native acceptance evidence', 1)[1]
        self.assertIn('runtime/portable-smoke/portable-smoke-report.json', evidence)
        self.assertIn('runtime/portable-smoke/offline-media/self-test-report.json', evidence)
        self.assertIn('if-no-files-found: error', evidence)
        for sensitive in ('provision.json', '.sqlite', 'launcher.log', '**', '.env'):
            self.assertNotIn(sensitive, evidence)

    def test_windows_archive_uses_native_zip_and_unix_preserves_symlinks(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/portable-package.yml').read_text()
        self.assertIn("'zip' if os.name == 'nt' else 'gztar'", workflow)
        self.assertIn('path: runtime/Youji-${{ matrix.label }}.*', workflow)

    def test_browser_system_packages_only_on_linux_without_skipping_native_smoke(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/portable-package.yml').read_text()
        linux = workflow.split('name: Install Linux rendering browser and system libraries', 1)[1].split('      - name:', 1)[0]
        self.assertIn("if: runner.os == 'Linux'", linux)
        self.assertIn('install --with-deps chromium', linux)
        native = workflow.split('name: Install Windows or macOS rendering browser', 1)[1].split('      - run:', 1)[0]
        self.assertIn("if: runner.os != 'Linux'", native)
        self.assertIn('install chromium', native)
        self.assertNotIn('--with-deps', native)
        self.assertIn('scripts/portable_smoke.py --executable', workflow)

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

    def test_private_instructions_follow_bundle_system_and_architecture(self):
        cases=[('win32','AMD64','启动有迹.cmd','%LOCALAPPDATA%\\Youji'),
               ('darwin','arm64','启动有迹.command','~/Library/Application Support/Youji'),
               ('linux','x86_64','./start-youji.sh','$XDG_DATA_HOME/youji')]
        for system,architecture,startup,directory in cases:
            with self.subTest(system=system),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);(root/('Youji.exe' if system=='win32' else 'Youji')).touch()
                (root/'build-manifest.json').write_text(json.dumps({'platform':system,'architecture':architecture}))
                provision(root,'synthetic-private-key')
                text=(root/'使用说明.txt').read_text()
                for required in (startup,directory,architecture,'launcher.log','本机账号','一次性恢复码','需要联网','关闭窗口结束API和Worker','未随本包安装','现有Mac独立实验环境不受影响'):
                    self.assertIn(required,text)
                self.assertNotIn('synthetic-private-key',text)
                self.assertNotIn('Windows 10实测',text)
                self.assertNotIn('所有Linux已通过',text)
                if system=='linux':self.assertIn('chmod +x start-youji.sh Youji',text)
                if system=='darwin':self.assertIn('勿关闭全局安全检查',text)

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

    def test_failure_diagnostics_never_uploads_temporary_user_database(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/portable-package.yml').read_text()
        diagnostics = workflow.split('name: Preserve synthetic smoke failure diagnostics', 1)[1].split('      - name:', 1)[0]
        self.assertIn('if: failure()', diagnostics)
        self.assertIn('runtime/portable-smoke/launcher-smoke.log', diagnostics)
        self.assertIn('runtime/portable-smoke/diagnostic.json', diagnostics)
        for sensitive in ('provision.json', '.sqlite', '**', '.env', 'user/'):
            self.assertNotIn(sensitive, diagnostics)

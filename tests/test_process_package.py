"""Check history export, credential removal and archive provenance end to end."""
import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.package_process import PREFIX, build, sanitize


class ProcessPackageTests(unittest.TestCase):
    def test_all_branch_history_and_deleted_secret_are_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def git(*args):
                return subprocess.run(['git', '-C', folder, *args], check=True,
                                      capture_output=True).stdout.decode().strip()

            git('init', '-q')
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            secret = 'sk-' + 'Z' * 30
            (root / 'draft.md').write_text('original draft\n' + secret)
            (root / '.env').write_text('DO_NOT_EXPORT=private')
            (root / 'runtime').mkdir()
            (root / 'runtime/data.json').write_text('private runtime')
            git('add', '.')
            git('commit', '-qm', 'first experiment')
            initial = git('rev-parse', 'HEAD')
            (root / 'draft.md').unlink()
            (root / 'README.md').write_text('current source\n')
            git('add', '-A')
            git('commit', '-qm', 'remove failed draft')
            git('branch', 'side', initial)
            git('checkout', '-q', 'side')
            (root / 'side.md').write_text('branch experiment\n')
            git('add', '.')
            git('commit', '-qm', 'side experiment')
            git('checkout', '-q', '-')
            try:
                (root / 'link.md').symlink_to(root / '.env')
            except OSError as exc:
                if getattr(exc, 'winerror', None) == 1314:
                    self.skipTest('Windows symbolic-link privilege unavailable; full case runs on Linux')
                raise
            output = root / 'output/process.zip'
            result = build(output, root=root, extras=('link.md',))
            self.assertEqual(result['commits'], 3)
            with zipfile.ZipFile(output) as archive:
                self.assertIsNone(archive.testzip())
                names = archive.namelist()
                self.assertFalse(any('/.env' in n or '/runtime/' in n or '/link.md' in n for n in names))
                self.assertNotIn(PREFIX + '/项目原文件/draft.md', names)
                data = b'\n'.join(archive.read(n) for n in names)
                self.assertNotIn(secret.encode(), data)
                self.assertNotIn(b'private runtime', data)
                self.assertNotIn(b'fixture@example.invalid', data)
                self.assertIn(b'side experiment', data)
                self.assertIn(b'original draft', data)
                manifest = json.loads(archive.read(PREFIX + '/MATERIAL_MANIFEST.json'))
                self.assertTrue(manifest['redactions'])
                for name, record in manifest['files'].items():
                    self.assertEqual(hashlib.sha256(archive.read(PREFIX + '/' + name)).hexdigest(), record['sha256'])
            self.assertIn(result['sha256'], output.with_suffix('.zip.sha256').read_text())

    def test_private_key_body_is_removed(self):
        data = b'-----BEGIN PRIVATE KEY-----\nQUJDREVG\n-----END PRIVATE KEY-----'
        clean, count = sanitize(data)
        self.assertGreater(count, 0)
        self.assertNotIn(b'QUJDREVG', clean)

    def test_reject_overwriting_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(['git', 'init', '-q', folder], check=True)
            (root / 'README.md').write_text('source')
            subprocess.run(['git', '-C', folder, 'add', '.'], check=True)
            subprocess.run(['git', '-C', folder, '-c', 'user.name=Fixture',
                            '-c', 'user.email=fixture@example.invalid',
                            'commit', '-qm', 'initial'], check=True)
            with self.assertRaises(ValueError):
                build(root / 'README.md', root=root)
            self.assertEqual((root / 'README.md').read_text(), 'source')

"""Portable packager unit tests use fake runtimes, never claim native acceptance."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts.package_teacher import PackageError, build, secret_candidates


class TeacherPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'source'
        self.repo.mkdir()
        self.site = self.root / 'site-packages'
        self.site.mkdir()
        self.embed = self.root / 'python-3.12.10-embed-amd64.zip'
        with zipfile.ZipFile(self.embed, 'w') as archive:
            for name in ['python.exe', 'python3.dll', 'python312.dll', 'python312.zip',
                         'python312._pth', '_sqlite3.pyd', 'sqlite3.dll', 'LICENSE.txt']:
                archive.writestr(name, 'fake-runtime-fixture')
        self.write('scripts/teacher_launcher.py', '# launcher fixture\n')
        self.write('packaging/teacher/start.cmd', '@echo off\r\n')
        self.write('packaging/teacher/README.txt', 'Teacher instructions\n')
        self.write('packaging/teacher/sample-product.txt', 'Synthetic product\n')
        self.write('backend/credentials.py', '# security source must be included\n')
        self.write('requirements.txt', 'sample==1.0\n')
        self.write('tests/test_sample.py', '# tests are reproducible source\n')
        self.write('docs/design/design_contract.json', '{}\n')
        self.write('config/creation_taxonomy.json', '{}\n')
        self.dep('sample/__init__.py', 'VALUE = 1\n')
        self.dep('sample-1.0.dist-info/METADATA', 'Name: sample\nVersion: 1.0\n')
        self.dep('sample-1.0.dist-info/licenses/LICENSE', 'license text')
        self.dep('certifi/cacert.pem', '-----BEGIN CERTIFICATE-----\npublic-ca-fixture\n-----END CERTIFICATE-----\n')
        self.dep('langchain_core/outputs/__init__.py', '# namespace not repository output\n')
        self.git('init', '-q')
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
        self.output = self.root / 'delivery.zip'

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], check=True, capture_output=True).stdout

    def write(self, name, data):
        target = self.repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data, encoding='utf-8')
        return target

    def dep(self, name, data):
        target = self.site / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data, encoding='utf-8')
        return target

    def package(self, **kwargs):
        return build(self.output, self.embed, self.site, self.repo, **kwargs)

    def test_complete_manifest_hash_licenses_layout_and_clean_state(self):
        result = self.package()
        self.assertFalse(result['source_dirty'])
        self.assertEqual(result['python_version'], '3.12.10')
        self.assertEqual(result['sha256'], hashlib.sha256(self.output.read_bytes()).hexdigest())
        with zipfile.ZipFile(self.output) as archive:
            names = archive.namelist()
            manifest = json.loads(archive.read('MANIFEST.json'))
            self.assertEqual(set(manifest['files']) | {'MANIFEST.json'}, set(names))
            for name, expected in manifest['files'].items():
                data = archive.read(name)
                self.assertEqual(expected, {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
            self.assertIn('app/backend/credentials.py', names)
            self.assertIn('app/docs/design/design_contract.json', names)
            self.assertIn('app/config/creation_taxonomy.json', names)
            self.assertIn('python/Lib/site-packages/sample-1.0.dist-info/licenses/LICENSE', names)
            self.assertIn('python/Lib/site-packages/certifi/cacert.pem', names)
            self.assertIn('一键启动.cmd', names)
            self.assertIn('先读我.txt', names)
            self.assertIn('示例产品资料.txt', names)
            self.assertFalse(any(name.startswith('data/') for name in names))
            self.assertEqual(archive.read('python/python312._pth'), b'python312.zip\n.\nLib/site-packages\n../app\nimport site\n')
            self.assertEqual(self.output.with_suffix('.zip.manifest.json').read_bytes(), archive.read('MANIFEST.json'))
        self.assertTrue(self.output.with_suffix('.zip.sha256').read_text(encoding='utf-8').startswith(result['sha256']))

    def test_tracked_state_and_nested_outputs_excluded_new_files_explicit(self):
        for name in ['.env', 'runtime/account.db', '.venv/secret.py', 'output/old.zip',
                     'docs/nested/archive.zip', 'data/private.txt', 'node_modules/index.js',
                     'browser_state/cookies.json', 'db/app.sqlite3', 'config/credentials.json']:
            self.write(name, 'do not ship')
            self.git('add', '-f', name)
        self.write('scripts/new_package.py', '# explicit addition\n')
        self.write('notes-untracked.txt', 'never automatically included')
        result = self.package(include_new=['scripts/new_package.py'])
        self.assertTrue(result['source_dirty'])
        with zipfile.ZipFile(self.output) as archive:
            names = archive.namelist()
            self.assertIn('app/scripts/new_package.py', names)
            self.assertNotIn('app/notes-untracked.txt', names)
            self.assertNotIn('app/.env', names)
            self.assertFalse(any('account.db' in name or 'old.zip' in name for name in names))
            manifest = json.loads(archive.read('MANIFEST.json'))
            self.assertEqual(manifest['included_untracked'], ['scripts/new_package.py'])
            self.assertIn('.env', manifest['excluded_tracked_paths'])

    def test_build_tools_and_cache_are_removed(self):
        for name in ['pip/__init__.py', 'pip-1.0.dist-info/METADATA', 'setuptools/__init__.py',
                     'wheel/__init__.py', 'build/__init__.py', '_distutils_hack/__init__.py',
                     'sample/__pycache__/thing.pyc', 'sample/other.pyc']:
            self.dep(name, 'unused build cache')
        self.package()
        with zipfile.ZipFile(self.output) as archive:
            self.assertFalse(any('/pip' in n or '/setuptools/' in n or '/build/' in n or n.endswith('.pyc') for n in archive.namelist()))

    def test_no_overwrite_any_existing_output_or_sidecar(self):
        for suffix in ['', '.sha256', '.manifest.json']:
            with self.subTest(suffix=suffix):
                target = Path(str(self.output) + suffix)
                target.write_bytes(b'keep')
                with self.assertRaisesRegex(PackageError, 'already exists'):
                    self.package()
                self.assertEqual(target.read_bytes(), b'keep')
                target.unlink()

    def test_unsafe_explicit_paths_cannot_bypass_exclusions(self):
        for name in ['../outside.txt', '/absolute.txt', 'C:/absolute.txt', 'docs/CON', '.env', 'runtime/a.txt']:
            with self.subTest(name=name), self.assertRaises(PackageError):
                self.package(include_new=[name])
        self.assertFalse(self.output.exists())

    def test_secret_candidate_refused_without_printing_value_even_in_tests(self):
        value = 'sk-' + 'aB19CdefGhJkLmN2QrsTuVwxyZ987654'
        self.write('tests/leaked.py', 'API_KEY = ' + repr(value))
        with self.assertRaises(PackageError) as error:
            self.package(include_new=['tests/leaked.py'])
        self.assertNotIn(value, str(error.exception))
        self.assertIn('tests/leaked.py', str(error.exception))
        self.assertFalse(self.output.exists())

    def test_placeholder_recognition_is_not_a_test_directory_blanket(self):
        self.assertEqual(secret_candidates('app/tests/example.py', b'API_KEY="test-fixture-not-a-key"'), [])
        fixture = b"data=b'-----BEGIN " + b"PRIVATE KEY-----\\nQUJDREVG\\n-----END PRIVATE KEY-----'"
        self.assertEqual(secret_candidates('app/tests/test_process_package.py', fixture), [])
        value = b'3abf23986' + b'df4683bd781297361b'
        self.assertTrue(secret_candidates('app/backend/live.py', b'API_KEY="' + value + b'"'))
        self.assertTrue(secret_candidates('app/.env.example', b'API_KEY=' + value))
        self.assertTrue(secret_candidates('app/config.json', b'{"API_KEY":"' + value + b'"}'))

    def test_dependency_path_files_local_provenance_and_wrong_abi_refused(self):
        cases = [('unsafe.pth', 'C:/Users/person/private'),
                 ('other.egg-link', '../../outside'),
                 ('sample-1.0.dist-info/direct_url.json', '{"url":"file:///C:/local"}'),
                 ('wrong.cp313-win_amd64.pyd', 'wrong ABI')]
        for name, data in cases:
            with self.subTest(name=name):
                file = self.dep(name, data)
                with self.assertRaises(PackageError):
                    self.package()
                file.unlink()

    def test_archive_traversal_duplicate_and_missing_runtime_refused(self):
        for extra in ['../escape.dll', 'python.exe', 'C:/escape.dll', '.env', 'data/state.db']:
            with self.subTest(extra=extra):
                bad = self.root / 'bad.zip'
                with zipfile.ZipFile(self.embed) as source, zipfile.ZipFile(bad, 'w') as target:
                    for item in source.infolist():
                        target.writestr(item, source.read(item))
                    target.writestr(extra, 'bad')
                with self.assertRaises(PackageError):
                    build(self.output, bad, self.site, self.repo, python_embed_version='3.12.10')
        with zipfile.ZipFile(bad, 'w') as target:
            target.writestr('python.exe', 'incomplete')
        with self.assertRaisesRegex(PackageError, 'Incomplete'):
            build(self.output, bad, self.site, self.repo, python_embed_version='3.12.10')

    def test_dependency_symlink_or_reparse_refused(self):
        # Simulate the Windows reparse bit: this test does not require symlink privileges.
        original = Path.lstat
        bad_path = self.site / 'sample' / '__init__.py'
        def attributes(path):
            result = original(path)
            if path == bad_path:
                class ReparseStat:
                    st_mode = result.st_mode
                    st_file_attributes = 0x400
                return ReparseStat()
            return result
        with patch.object(Path, 'lstat', attributes), self.assertRaisesRegex(PackageError, 'reparse'):
            self.package()

    def test_source_changes_after_scan_fail_closed_and_remove_partial_outputs(self):
        original = zipfile.ZipFile.writestr
        changed = False
        def write(archive, name, data, *args, **kwargs):
            nonlocal changed
            if not changed and archive.filename == str(self.output):
                changed = True
                self.write('requirements.txt', 'changed-after-preflight')
            return original(archive, name, data, *args, **kwargs)
        with patch.object(zipfile.ZipFile, 'writestr', write), self.assertRaisesRegex(PackageError, 'changed after'):
            self.package()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_suffix('.zip.sha256').exists())
        self.assertFalse(self.output.with_suffix('.zip.manifest.json').exists())

    def test_identical_inputs_produce_identical_archives(self):
        first = self.package()
        self.output = self.root / 'another.zip'
        second = self.package()
        self.assertEqual(first['sha256'], second['sha256'])


if __name__ == '__main__':
    unittest.main()

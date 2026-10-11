"""Real filesystem ACL/mode, secret creation races and process-lock regressions."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.contracts import DomainError
from backend.credentials import CredentialVault
from backend.file_lock import exclusive_file_lock
from backend.private_files import is_private_file, private_binary_file, write_private_bytes


ROOT = Path(__file__).resolve().parents[1]
LOCK_CHILD = '''
import sys
from backend.file_lock import exclusive_file_lock
try:
    with exclusive_file_lock(sys.argv[1]):
        pass
except BlockingIOError:
    sys.exit(73)
'''


class PrivateFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.path = self.folder / '私密文件.key'

    def test_permissions_are_private_before_the_first_byte_is_written(self):
        with private_binary_file(self.path) as handle:
            self.assertEqual(self.path.stat().st_size, 0)
            self.assertTrue(is_private_file(self.path))
            handle.write(b'fixture-secret')
        self.assertEqual(self.path.read_bytes(), b'fixture-secret')
        if os.name == 'nt':
            # Independent Windows utility confirms the on-disk protected DACL.
            # This is not a mocked permission check or a POSIX mode-bit assertion.
            from backend.windows_private_file import current_sid
            acl = self.folder / 'acl.txt'
            result = subprocess.run(['icacls', str(self.path), '/save', str(acl)],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0)
            descriptor = acl.read_text(encoding='utf-16-le').splitlines()[1]
            self.assertEqual(descriptor, f'D:P(A;;FA;;;{current_sid()})')
        else:
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_broad_permissions_are_rejected_without_overwriting_existing_key(self):
        store = SimpleNamespace(postgres=False, path=self.folder / 'test.sqlite')
        vault = CredentialVault(store, environ={})
        encrypted = vault.encrypt('only-fixture')
        path = self.folder / 'credentials.key'
        original = path.read_bytes()
        if os.name == 'nt':
            result = subprocess.run(['icacls', str(path), '/grant', '*S-1-1-0:R'],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0)
        else:
            os.chmod(path, 0o644)
        self.assertFalse(is_private_file(path))
        with self.assertRaises(DomainError) as caught:
            vault.decrypt(encrypted)
        self.assertEqual(caught.exception.code, 'CONFIG_INVALID')
        self.assertEqual(path.read_bytes(), original)

    def test_atomic_create_does_not_clobber_and_leaves_no_temporary_file(self):
        write_private_bytes(self.path, b'original')
        with self.assertRaises(FileExistsError):
            write_private_bytes(self.path, b'other')
        self.assertEqual(self.path.read_bytes(), b'original')
        self.assertEqual(list(self.folder.iterdir()), [self.path])
        write_private_bytes(self.path, '替换'.encode('utf-8'), replace=True)
        self.assertTrue(is_private_file(self.path))
        self.assertEqual(self.path.read_text(encoding='utf-8'), '替换')

    def test_permission_verification_failure_writes_no_secret(self):
        with patch('backend.private_files.is_private_file', return_value=False):
            with self.assertRaises(PermissionError):
                write_private_bytes(self.path, b'never-written')
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_concurrent_vault_initialization_keeps_one_decryptable_key(self):
        store = SimpleNamespace(postgres=False, path=self.folder / 'test.sqlite')
        def encrypt(number):
            return CredentialVault(store, environ={}).encrypt(str(number))
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(encrypt, range(12)))
        vault = CredentialVault(store, environ={})
        self.assertEqual([vault.decrypt(value) for value in values], list(map(str, range(12))))
        self.assertEqual([p.name for p in self.folder.iterdir()], ['credentials.key'])

    def test_missing_directory_and_reparse_files_fail_closed(self):
        self.assertFalse(is_private_file(self.path))
        self.assertFalse(is_private_file(self.folder))
        info = SimpleNamespace(st_mode=0o100600, st_file_attributes=0x400)
        with patch.object(Path, 'lstat', return_value=info):
            self.assertFalse(is_private_file(self.path))

    def child(self):
        return subprocess.run([sys.executable, '-X', 'utf8', '-B', '-c', LOCK_CHILD,
                               str(self.path)], cwd=ROOT, capture_output=True, timeout=10)

    def test_reader_lock_excludes_other_process_and_releases_after_exception(self):
        with self.assertRaisesRegex(ValueError, 'fixture'):
            with exclusive_file_lock(self.path):
                self.assertEqual(self.child().returncode, 73)
                raise ValueError('fixture')
        self.assertEqual(self.child().returncode, 0)


if __name__ == '__main__':
    unittest.main()

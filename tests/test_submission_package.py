"""A release archive must retain the source version its evidence actually hashes."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('submission_package', ROOT / 'scripts/package_submission.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class SubmissionPackageTests(unittest.TestCase):
    def prepare(self, root):
        evidence = root / 'docs/submission/evidence'
        evidence.mkdir(parents=True)
        (root / 'output/pdf').mkdir(parents=True)
        checks = {}
        for i in range(6):
            name = str(i) + '.pdf'
            raw = b'verified PDF ' + str(i).encode()
            (root / 'output/pdf' / name).write_bytes(raw)
            checks[name] = {'sha256': hashlib.sha256(raw).hexdigest()}
        (evidence / 'pdf-checks.json').write_text(json.dumps(checks))
        old = b'baseline source, distinct from current product'
        archive = evidence / 'baseline-source/backend/api.py.snapshot'
        archive.parent.mkdir(parents=True)
        archive.write_bytes(old)
        (evidence / 'source-manifest.json').write_text(json.dumps({'backend/api.py': hashlib.sha256(old).hexdigest()}))
        (root / 'backend').mkdir()
        (root / 'backend/api.py').write_bytes(b'current product source')
        (root / 'docs/submission/00_guide.md').write_text('current editable guide')
        (root / 'docs/REAL_WORKFLOW_ACCEPTANCE_20261004.md').write_text('latest acceptance summary')
        (root / 'scripts').mkdir()
        for name in ('build_submission_docs.py', 'package_submission.py'):
            (root / 'scripts' / name).write_text('# source builder')
        return archive

    def test_packaging_new_code_uses_verified_historical_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = self.prepare(root)
            with patch.object(package, 'ROOT', root), contextlib.redirect_stdout(io.StringIO()):
                package.build()
            with zipfile.ZipFile(root / 'output' / (package.NAME + '.zip')) as result:
                name = package.NAME + '/历史核验依据/backend/api.py.snapshot'
                self.assertEqual(result.read(name), archive.read_bytes())
                self.assertNotIn(package.NAME + '/核验依据/backend/api.py', result.namelist())
                readme = result.read(package.NAME + '/请先阅读.txt').decode()
                self.assertIn('2026-09-21', readme)
                self.assertIn('441359e', readme)
                self.assertIn('不能将空白表或AI模拟当真人反馈', readme)
                self.assertIn(package.NAME + '/最新验收摘要/REAL_WORKFLOW_ACCEPTANCE_20261004.md', result.namelist())
                self.assertIsNone(result.testzip())

    def test_changed_historical_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root).write_bytes(b'tampered baseline')
            with patch.object(package, 'ROOT', root), self.assertRaises(AssertionError):
                package.build()

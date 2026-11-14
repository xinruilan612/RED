"""Check publication integrity and reject a changed or escaping manifest member."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from scripts.verify_source_release import verify


class SourceReleaseManifestTests(unittest.TestCase):
    def test_delivered_source_matches_manifest(self):
        self.assertGreater(verify(Path(__file__).resolve().parents[1]), 1000)

    def test_modified_source_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.joinpath('sample.py').write_bytes(b'after')
            manifest = {'files': {'sample.py': {'bytes': 6, 'sha256': hashlib.sha256(b'before').hexdigest()}}}
            root.joinpath('SOURCE_MANIFEST_20261105.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'Source hash mismatch'):
                verify(root)

    def test_manifest_cannot_read_outside_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.joinpath('SOURCE_MANIFEST_20261105.json').write_text(json.dumps({'files': {'../outside': {}}}))
            with self.assertRaisesRegex(ValueError, 'Unsafe manifest path'):
                verify(root)

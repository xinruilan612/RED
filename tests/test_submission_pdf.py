"""Require actual delivery PDFs to match their reviewed manuscripts and manifest."""
import hashlib
import json
from pathlib import Path
import unittest
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]


class SubmissionPDFTests(unittest.TestCase):
    def test_six_verified_pdfs_match_current_sources(self):
        checks = json.loads((ROOT / 'docs/submission/evidence/pdf-checks.json').read_text())
        self.assertEqual(len(checks), 6)
        for name, record in checks.items():
            with self.subTest(document=name):
                pdf = ROOT / 'output/pdf' / name
                source = ROOT / record['source']
                self.assertEqual(hashlib.sha256(pdf.read_bytes()).hexdigest(), record['sha256'])
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), record['source_sha256'])
                reader = PdfReader(pdf)
                self.assertEqual(len(reader.pages), record['pages'])
                self.assertEqual(pdf.stat().st_size, record['bytes'])
                self.assertLess(pdf.stat().st_size, 10_000_000)
                self.assertIn('47191919', reader.pages[0].extract_text())
                self.assertTrue(all(len(page.extract_text()) > 100 for page in reader.pages))
                self.assertEqual(record['text_checks'], 'passed')
                self.assertIn('rendered', record['visual_review'])


if __name__ == '__main__':
    unittest.main()

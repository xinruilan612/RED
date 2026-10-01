"""Exercise parser IPC without Unix resource or a UTF-8 console locale."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import zipfile

from backend.document_parser import apply_resource_limits


ROOT = Path(__file__).resolve().parents[1]


def pdf_bytes(pages=1):
    from pypdf import PdfWriter
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class ParserPortabilityTests(unittest.TestCase):
    def run_parser(self, module, raw, without_resource=False):
        # A separate interpreter preserves the real binary stdin/stdout contract.
        # None in sys.modules reproduces Windows' unavailable resource module.
        script = (
            "import sys, runpy; "
            + ("sys.modules['resource'] = None; " if without_resource else "")
            + f"runpy.run_module({module!r}, run_name='__main__')"
        )
        result = subprocess.run(
            [sys.executable, '-c', script], input=raw, capture_output=True,
            cwd=ROOT, timeout=12,
            env={**os.environ, 'PYTHONIOENCODING': 'ascii'},
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode('ascii', errors='replace'))
        self.assertTrue(result.stdout.isascii())
        return json.loads(result.stdout)

    def test_pdf_parses_when_unix_resource_is_unavailable(self):
        result = self.run_parser('backend.document_parser', pdf_bytes(), True)
        self.assertEqual(result, {'pages': [[1, '']]})

    def test_pdf_page_limit_still_applies_without_resource(self):
        result = self.run_parser('backend.document_parser', pdf_bytes(51), True)
        self.assertIn('error', result)
        self.assertIn('50页', result['error'])

    def test_invalid_pdf_error_survives_non_utf8_stdout(self):
        result = self.run_parser('backend.document_parser', b'broken', True)
        self.assertIn('无法读取 PDF', result['error'])

    def test_docx_chinese_and_emoji_survive_non_utf8_stdout(self):
        output = io.BytesIO()
        text = '护肤步骤：洁面、保湿，再防晒。🌞'
        xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/'
               'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
               + text + '</w:t></w:r></w:p></w:body></w:document>')
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('[Content_Types].xml', '<Types/>')
            archive.writestr('word/document.xml', xml)
        result = self.run_parser('backend.word_parser', output.getvalue())
        self.assertEqual(result, {'paragraphs': [[1, text]]})

    def test_docx_error_survives_non_utf8_stdout(self):
        result = self.run_parser('backend.word_parser', b'broken')
        self.assertIn('无法读取 DOCX', result['error'])

    def test_unix_limits_are_retained(self):
        from unittest.mock import Mock
        resource = Mock(RLIMIT_CPU=0, RLIMIT_AS=9)
        with patch.dict(sys.modules, {'resource': resource}):
            apply_resource_limits()
        self.assertEqual(resource.setrlimit.call_count, 2)
        resource.setrlimit.assert_any_call(0, (8, 8))
        resource.setrlimit.assert_any_call(9, (768*1024*1024, 768*1024*1024))


if __name__ == '__main__':
    unittest.main()

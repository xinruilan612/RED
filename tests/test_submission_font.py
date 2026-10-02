"""Font selection contracts without adding ReportLab to application requirements."""
import importlib.util
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'build_submission_docs.py'


def load_with_stubbed_pdf_runtime():
    names = ('reportlab', 'reportlab.pdfbase', 'reportlab.pdfbase.pdfmetrics',
             'reportlab.pdfbase.ttfonts', 'reportlab.lib', 'reportlab.lib.colors',
             'reportlab.lib.styles', 'reportlab.platypus', 'reportlab.lib.pagesizes')
    modules = {name: ModuleType(name) for name in names}
    modules['reportlab.pdfbase.ttfonts'].TTFont = Mock()
    modules['reportlab.pdfbase.ttfonts'].TTFError = type('TTFError', (Exception,), {})
    modules['reportlab.pdfbase.pdfmetrics'].registerFont = Mock()
    modules['reportlab.lib.styles'].ParagraphStyle = Mock()
    modules['reportlab.lib.pagesizes'].A4 = (595, 842)
    for name in ('SimpleDocTemplate', 'Paragraph', 'Spacer', 'Table', 'TableStyle', 'PageBreak'):
        setattr(modules['reportlab.platypus'], name, Mock())
    modules['reportlab.platypus'].Flowable = type('Flowable', (), {})
    spec = importlib.util.spec_from_file_location('submission_font_contract', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    with patch.dict('sys.modules', modules):
        spec.loader.exec_module(module)
    return module


class SubmissionFontTests(unittest.TestCase):
    def setUp(self):
        self.builder = load_with_stubbed_pdf_runtime()
        self.font = SimpleNamespace(face=SimpleNamespace(
            charToGlyph={ord(char): 1 for char in ('中文有迹软件创新测试' + self.builder.FIXED_RENDER_TEXT)}))
        self.builder.TTFont.return_value = self.font
        self.environment = patch.dict(self.builder.os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def candidate(self, name):
        path = self.root / name
        path.touch()
        return path

    def test_valid_installed_candidate_is_registered_after_missing_path(self):
        font = self.candidate('installed.ttc')
        with patch.object(self.builder, 'cjk_font_candidates', return_value=(self.root / 'missing.ttf', font)):
            self.assertEqual(self.builder.register_cjk_font(required_text='测试'), font)
        self.builder.TTFont.assert_called_once_with('CN', str(font), subfontIndex=0)
        self.builder.pdfmetrics.registerFont.assert_called_once_with(self.font)

    def test_original_mac_font_remains_first_and_candidates_cover_platforms(self):
        paths = self.builder.cjk_font_candidates()
        self.assertEqual(paths[0], Path('/System/Library/Fonts/STHeiti Light.ttc'))
        self.assertIn(Path('C:/Windows/Fonts/msyh.ttc'), paths)
        self.assertIn(Path('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'), paths)

    def test_missing_fonts_fail_with_configuration_guidance(self):
        with patch.object(self.builder, 'cjk_font_candidates', return_value=(self.root / 'absent.ttf',)):
            with self.assertRaisesRegex(ValueError, 'SUBMISSION_CJK_FONT'):
                self.builder.register_cjk_font()
        self.builder.pdfmetrics.registerFont.assert_not_called()

    def test_explicit_valid_font_takes_priority(self):
        font = self.candidate('chosen.ttf')
        with patch.object(self.builder, 'cjk_font_candidates') as defaults:
            self.assertEqual(self.builder.register_cjk_font(font), font)
        defaults.assert_not_called()

    def test_empty_environment_value_uses_installed_candidates(self):
        font = self.candidate('installed.ttf')
        with patch.dict(self.builder.os.environ, {'SUBMISSION_CJK_FONT': ''}), \
                patch.object(self.builder, 'cjk_font_candidates', return_value=(font,)):
            self.assertEqual(self.builder.register_cjk_font(), font)
        self.builder.pdfmetrics.registerFont.assert_called_once_with(self.font)

    def test_fixed_diagram_and_footer_glyphs_are_checked(self):
        path = self.candidate('incomplete.ttf')
        del self.font.face.charToGlyph[ord('洞')]
        with self.assertRaisesRegex(ValueError, 'required glyphs'):
            self.builder.register_cjk_font(path, required_text='测试')
        self.builder.pdfmetrics.registerFont.assert_not_called()

    def test_invalid_explicit_configuration_does_not_fallback_or_echo_path(self):
        configured = str(self.root / 'private-configuration-marker.ttf')
        with patch.dict(self.builder.os.environ, {'SUBMISSION_CJK_FONT': configured}), \
                patch.object(self.builder, 'cjk_font_candidates') as defaults:
            with self.assertRaises(ValueError) as raised:
                self.builder.register_cjk_font()
        self.assertIn('Configured font', str(raised.exception))
        self.assertNotIn(configured, str(raised.exception))
        defaults.assert_not_called()
        self.builder.pdfmetrics.registerFont.assert_not_called()

    def test_unreadable_or_unsupported_default_candidate_tries_next(self):
        first, second = self.candidate('unsupported.ttc'), self.candidate('supported.ttf')
        self.builder.TTFont.side_effect = [self.builder.TTFError('invalid font'), self.font]
        with patch.object(self.builder, 'cjk_font_candidates', return_value=(first, second)):
            self.assertEqual(self.builder.register_cjk_font(), second)
        self.builder.pdfmetrics.registerFont.assert_called_once_with(self.font)

    def test_font_without_required_glyphs_is_not_silently_used(self):
        path = self.candidate('latin-only.ttf')
        self.builder.TTFont.return_value = SimpleNamespace(face=SimpleNamespace(charToGlyph={}))
        with self.assertRaisesRegex(ValueError, 'required glyphs'):
            self.builder.register_cjk_font(path)
        self.builder.pdfmetrics.registerFont.assert_not_called()


if __name__ == '__main__':
    unittest.main()

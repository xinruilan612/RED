"""Real Chromium scene geometry and preview/export identity; no model calls."""
import base64
from io import BytesIO
import unittest
import zipfile
from PIL import Image
from backend.card_layout import normalize_options
from backend.contracts import DomainError
from backend.media_exports import preview_run, export_run
from tests.test_html_cards import product_run


def upload():
    stream = BytesIO()
    Image.new('RGB', (320, 220), '#e58459').save(stream, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()


class StudioRenderTests(unittest.TestCase):
    def setUp(self):
        self.run = product_run('① 连接：请核对电脑接口。\n\n② 携带：机身小巧，适合随身携带。')

    def test_combined_edits_preserve_copy_and_preview_export_exact_bytes(self):
        before = preview_run(self.run, 'xhs-a')
        options = {'studio': {'pages': {'0': {'image': {'scale': 1.08}, 'title': {'dy': -15, 'color': '#224466'}}}}}
        after = preview_run(self.run, 'xhs-a', options)
        self.assertNotEqual(before['pages'][0]['sha256'], after['pages'][0]['sha256'])
        self.assertEqual(before['pages'][1]['sha256'], after['pages'][1]['sha256'])
        images = lambda p: next(e for e in p['elements'] if e['id'] == 'image')['bounds']
        self.assertAlmostEqual(images(after['pages'][0])['width'] / images(before['pages'][0])['width'], 1.08, places=3)
        self.assertEqual([p['text_blocks'] for p in before['pages']], [p['text_blocks'] for p in after['pages']])
        data, _, _ = export_run(self.run, 'images', template='xhs-a', options=options, expected_design_hash=after['design_hash'])
        with zipfile.ZipFile(BytesIO(data)) as z:
            for page in after['pages']:
                self.assertEqual(z.read(page['name']), base64.b64decode(page['data_url'].split(',')[1]))

    def test_repeated_composed_preview_and_export_have_identical_pixels(self):
        # Fresh Chromium instances previously alternated 26 pixels on the cover's
        # decoration arc where the late page-number repaint intersected its edge.
        options = {'studio': {'pages': {'0': {'image': {'scale': 1.08}, 'title': {'dy': -15, 'color': '#224466'}}}}}
        first = preview_run(self.run, 'xhs-a', options)
        expected = {page['name']: base64.b64decode(page['data_url'].split(',')[1]) for page in first['pages']}
        for attempt in range(10):
            with self.subTest(attempt=attempt):
                if attempt % 2:
                    data, _, _ = export_run(self.run, 'images', template='xhs-a', options=options, expected_design_hash=first['design_hash'])
                    with zipfile.ZipFile(BytesIO(data)) as archive:
                        actual = {name: archive.read(name) for name in expected}
                else:
                    repeated = preview_run(self.run, 'xhs-a', options)
                    self.assertEqual(repeated['design_hash'], first['design_hash'])
                    actual = {page['name']: base64.b64decode(page['data_url'].split(',')[1]) for page in repeated['pages']}
                self.assertEqual(actual.keys(), expected.keys())
                for name in expected:
                    self.assertEqual(actual[name], expected[name])

    def test_three_layouts_are_distinct_and_preserve_all_text(self):
        hashes = set()
        for layout in ('hero', 'checklist', 'compare'):
            result = preview_run(self.run, 'xhs-a', {'studio': {'pages': {'0': {'layout': layout}, '1': {'layout': layout}}}})
            hashes.add(result['pages'][0]['sha256'])
            self.assertTrue(all(p['layout_verified'] for p in result['pages']))
            text = ''.join(''.join(p['text_blocks']) for p in result['pages'])
            self.assertEqual(text, self.run.drafts[0]['content']['body'].replace('\n', '') + self.run.drafts[0]['content']['cta'])
        self.assertEqual(len(hashes), 3)

    def test_page_specific_upload_overrides_catalog_without_replacing_other_pages(self):
        before = preview_run(self.run, 'xhs-a')
        options = {'studio': {'pages': {'1': {'image': {'asset_id': 'mine'}}}, 'assets': {'mine': upload()}}}
        after = preview_run(self.run, 'xhs-a', options)
        self.assertEqual(before['pages'][0]['sha256'], after['pages'][0]['sha256'])
        self.assertNotEqual(before['pages'][1]['sha256'], after['pages'][1]['sha256'])
        self.assertEqual(after['pages'][1]['photo_id'], 'mine')
        self.assertIsNone(after['pages'][1]['photo_source_url'])

    def test_default_transforms_leave_pixels_unchanged(self):
        before = preview_run(self.run, 'xhs-a')
        after = preview_run(self.run, 'xhs-a', {'studio': {'pages': {'0': {'image': {'scale': 1, 'dx': 0, 'dy': 0}}}}})
        self.assertEqual(before['pages'][0]['sha256'], after['pages'][0]['sha256'])
        self.assertEqual(before['pages'][0]['elements'], after['pages'][0]['elements'])

    def test_off_page_or_overlapping_edits_are_rejected(self):
        for patch in ({'title': {'dy': -350}}, {'image': {'scale': 1.6}}, {'image': {'dy': -350}, 'title': {'dy': 350}}):
            with self.subTest(patch=patch), self.assertRaises(DomainError):
                preview_run(self.run, 'xhs-a', {'studio': {'pages': {'0': patch}}})

    def test_full_bleed_product_background_true_text_alpha_and_restore(self):
        before = preview_run(self.run, 'xhs-a')
        options = {'studio': {'pages': {'1': {'image': {'placement': 'background'}, 'title': {'opacity': .5}, 'body': {'opacity': .5}}}}}
        after = preview_run(self.run, 'xhs-a', options)
        page = after['pages'][1]
        elements = {e['id']: e for e in page['elements']}
        self.assertEqual(elements['image']['bounds'], {'x': 0, 'y': 0, 'width': 1080, 'height': 1440})
        self.assertEqual(elements['image']['placement'], 'background')
        self.assertEqual(elements['body']['opacity'], .5)
        self.assertEqual(elements['title']['opacity'], .5)
        self.assertTrue(page['layout_verified'])
        self.assertEqual(before['pages'][0]['sha256'], after['pages'][0]['sha256'])
        self.assertEqual(before['pages'][1]['text_blocks'], page['text_blocks'])
        opaque = preview_run(self.run, 'xhs-a', {'studio': {'pages': {'1': {'image': {'placement': 'background'}}}}})
        self.assertNotEqual(opaque['pages'][1]['sha256'], page['sha256'])
        data, _, _ = export_run(self.run, 'images', template='xhs-a', options=options, expected_design_hash=after['design_hash'])
        with zipfile.ZipFile(BytesIO(data)) as archive:
            self.assertEqual(archive.read(page['name']), base64.b64decode(page['data_url'].split(',')[1]))
        restored = preview_run(self.run, 'xhs-a', {'studio': {'pages': {'1': {'image': {'placement': 'inline'}, 'title': {'opacity': 1}, 'body': {'opacity': 1}}}}})
        self.assertEqual(before['pages'][1]['sha256'], restored['pages'][1]['sha256'])

    def test_background_keeps_text_bounds_protection(self):
        with self.assertRaises(DomainError):
            preview_run(self.run, 'xhs-a', {'studio': {'pages': {'1': {'image': {'placement': 'background'}, 'title': {'dy': -350}}}}})

    def test_background_and_alpha_schema_are_strict(self):
        for patch in ({'image': {'placement': 'url(evil)'}}, {'image': {'opacity': .5}}, {'body': {'opacity': -1}}, {'title': {'opacity': 1.1}}, {'body': {'opacity': float('nan')}}, {'body': {'opacity': True}}):
            with self.subTest(patch=patch), self.assertRaises(DomainError):
                normalize_options({'studio': {'pages': {'1': patch}}})

    def test_schema_rejects_untrusted_properties_nonfinite_and_missing_assets(self):
        for studio in ({'pages': {'0': {'image': {'scale': float('nan')}}}}, {'pages': {'0': {'body': {'html': '<script>'}}}}, {'pages': {'0': {'background': {'color': 'url(x)'}}}}, {'pages': {'0': {'image': {'asset_id': 'missing'}}}}, {'assets': {'bad': 'https://example.org/a.png'}}, {'assets': {str(n): upload() for n in range(7)}}):
            with self.subTest(studio=str(studio)[:80]), self.assertRaises(DomainError):
                normalize_options({'studio': studio})
        normalized, _ = normalize_options({'studio': {'assets': {'good': upload()}}})
        again, _ = normalize_options(normalized)
        self.assertEqual(normalized, again)

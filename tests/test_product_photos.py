import base64
from io import BytesIO
import json
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image
from backend.media_exports import preview_run, export_run
from backend.product_photos import resolve_options, PHOTO
from tests.test_media_exports import fixture


class ProductPhotoTests(unittest.TestCase):
    def test_matches_only_explicit_exact_brand_model(self):
        for text in ('罗技 M185 鼠标', 'Logitech M185 mouse', '罗技M185'):
            options, photo = resolve_options({'content': {'body': text}})
            self.assertEqual(photo['author'], 'Hayden Schiff')
            self.assertTrue(options['cover_image'].startswith('data:image/jpeg;base64,'))
        for text in ('罗技 M1850', '罗技 M185S', '罗技 M186', '其他品牌 M185', '罗技 M186，对比 M185', 'MyLogitech M185'):
            self.assertIsNone(resolve_options({'content': {'body': text}})[1], text)

    def test_does_not_match_tags_or_override_upload_or_removal(self):
        snapshot = {'content': {'body': '罗技 M185'}}
        self.assertEqual(resolve_options(snapshot, {'cover_image': 'my-upload'})[0]['cover_image'], 'my-upload')
        self.assertIsNone(resolve_options(snapshot, {'cover_image': 'my-upload'})[1])
        self.assertIsNone(resolve_options(snapshot, {'product_photo': 'none'})[1])
        self.assertIsNone(resolve_options({'content': {'tags': ['罗技M185']}})[1])

    def test_local_photo_missing_does_not_fabricate(self):
        with patch('backend.product_photos.PHOTO_PATH') as path:
            path.is_file.return_value = False
            options, photo = resolve_options({'content': {'body': '罗技M185'}})
            self.assertIsNone(photo)
            self.assertNotIn('cover_image', options)

    def test_real_preview_export_match_and_photo_source_is_recorded(self):
        run = fixture('罗技 M185 通过 USB 接收器连接。')
        preview = preview_run(run)
        self.assertEqual(preview['product_photo']['id'], PHOTO['id'])
        self.assertGreaterEqual(len(preview['product_photo']['photos']), 1)
        data, _, _ = export_run(run, expected_design_hash=preview['design_hash'])
        with zipfile.ZipFile(BytesIO(data)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['product_photo']['license'], 'CC BY 4.0')
            self.assertIn('Hayden Schiff', archive.read('图片来源与许可.txt').decode())
            self.assertIn('image_sha256', manifest['design_options'])
            self.assertNotIn('cover_image', manifest['design_options'])
            for page in preview['pages']:
                self.assertEqual(base64.b64decode(page['data_url'].split(',', 1)[1]), archive.read(page['name']))
        no_photo = preview_run(run, options={'product_photo': 'none'})
        self.assertIsNone(no_photo['product_photo'])
        self.assertNotEqual(preview['design_hash'], no_photo['design_hash'])
        self.assertNotEqual(preview['pages'][0]['sha256'], no_photo['pages'][0]['sha256'])

    def test_user_upload_has_no_false_catalog_attribution(self):
        buf = BytesIO()
        Image.new('RGB', (20, 20), 'blue').save(buf, 'PNG')
        options = {'cover_image': 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()}
        result = preview_run(fixture('罗技M185鼠标'), options=options)
        self.assertIsNone(result['product_photo'])

    def test_complete_instructions_include_photo_credit(self):
        def video(snapshot, **kwargs):
            snapshot['video'] = {'audio': False}
            return [('video.mp4', b'fixture')]
        with patch('backend.media_exports._video', side_effect=video):
            data, _, _ = export_run(fixture('罗技 M185 鼠标'), 'complete')
        with zipfile.ZipFile(BytesIO(data)) as archive:
            instructions = archive.read('使用说明.txt').decode()
            self.assertIn('Hayden Schiff', instructions)
            self.assertIn('CC BY 4.0', instructions)
            self.assertIn('等比例缩放', instructions)


    def test_distinct_catalog_images_are_used_once_then_text_only(self):
        from backend.product_photos import CATALOG
        from PIL import ImageDraw
        from backend.media_exports import confirmed_snapshot
        run = fixture(('罗技 M185。① 接口：先核对USB接口。\n\n② 携带：外形小巧。\n\n③ 供电：实际受条件影响。\n\n') * 10)
        original = ImageDraw.ImageDraw.text
        for template in ('classic', 'checklist'):
            drawn = []
            def record(draw, xy, text, *args, **kwargs):
                if xy[0] == 112: drawn.append(text)
                return original(draw, xy, text, *args, **kwargs)
            with patch.object(ImageDraw.ImageDraw, 'text', record):
                preview = preview_run(run, template)
            photos = preview['product_photo']['photos']
            self.assertGreaterEqual(len(photos), 2, 'Verified different-angle assets must be present')
            self.assertGreater(preview['page_count'], len(photos))
            ids = [page['photo_id'] for page in preview['pages']]
            self.assertEqual(ids[:len(photos)], [photo['id'] for photo in photos])
            self.assertTrue(all(value is None for value in ids[len(photos):]))
            self.assertEqual(len({p['sha256'] for p in photos}), len(photos))
            self.assertEqual(preview['options']['photos'], [{'id': p['id'], 'sha256': p['sha256']} for p in photos])
            content = confirmed_snapshot(run)['content']
            for value in (content['body'], content['cta']):
                self.assertIn(value.replace('\n', ''), ''.join(drawn))
            for index, photo in enumerate(photos):
                self.assertEqual(preview['pages'][index]['photo_sha256'], photo['sha256'])
                self.assertEqual(preview['pages'][index]['photo_source_url'], photo['source_url'])

    def test_missing_extra_photos_never_repeat_first(self):
        from backend.product_photos import CATALOG
        with patch('backend.product_photos.CATALOG', CATALOG[:1]):
            preview = preview_run(fixture('罗技M185。' * 100))
        self.assertIsNotNone(preview['pages'][0]['photo_id'])
        self.assertTrue(all(page['photo_id'] is None for page in preview['pages'][1:]))

    def test_design_identity_binds_secondary_photo_bytes(self):
        from backend.media_exports import design_identity, confirmed_snapshot
        from backend.product_photos import resolve_options
        snapshot = confirmed_snapshot(fixture('罗技M185'))
        options, photo = resolve_options(snapshot)
        original = design_identity(snapshot, 'classic', None)[1]
        changed = {**photo, 'photos': [dict(p) for p in photo['photos']]}
        changed['photos'][-1]['sha256'] = '0' * 64
        with patch('backend.media_exports.resolve_options', return_value=(options, changed)):
            self.assertNotEqual(original, design_identity(snapshot, 'classic', None)[1])

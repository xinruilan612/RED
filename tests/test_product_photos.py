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
        self.assertEqual(preview['product_photo'], PHOTO)
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

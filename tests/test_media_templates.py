import base64
from io import BytesIO
import json
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image, ImageDraw
from backend.contracts import DomainError
from backend.media_exports import export_run, preview_run, confirmed_snapshot, render_images, _video
from tests.test_media_exports import fixture


class MediaTemplateTests(unittest.TestCase):
    def test_preview_matches_export_all_pages_and_binds_version(self):
        run = fixture('完整中文正文不能丢失。' * 50)
        outputs = []
        for template in ('classic', 'checklist'):
            preview = preview_run(run, template)
            data, _, _ = export_run(run, template=template)
            self.assertEqual(preview['draft_ref'], run.accepted_ref)
            self.assertEqual(preview['content_hash'], run.drafts[0]['content_hash'])
            self.assertGreater(preview['page_count'], 2)
            with zipfile.ZipFile(BytesIO(data)) as archive:
                manifest = json.loads(archive.read('manifest.json'))
                self.assertEqual(manifest['template_id'], template)
                self.assertEqual(manifest['template_version'], 3)
                for page in preview['pages']:
                    png = base64.b64decode(page['data_url'].split(',', 1)[1])
                    self.assertEqual(png, archive.read(page['name']))
                    self.assertEqual(Image.open(BytesIO(png)).size, (1080, 1440))
                outputs.append(archive.read('01.png'))
        self.assertNotEqual(*outputs)

    def test_global_style_colors_every_page_and_export_matches_without_upload(self):
        run=fixture('连接携带供电，逐项核对。' * 80)
        normal=preview_run(run)
        options={'global_style':{'accent':'orange','size':'large'}}
        changed=preview_run(run,options=options)
        self.assertEqual(len(normal['pages']),len(changed['pages']))
        data,_,_=export_run(run,options=options)
        with zipfile.ZipFile(BytesIO(data)) as archive:
            for before,after in zip(normal['pages'],changed['pages']):
                self.assertNotEqual(before['data_url'],after['data_url'])
                png=base64.b64decode(after['data_url'].split(',',1)[1])
                self.assertEqual(png,archive.read(after['name']))
        self.assertNotEqual(normal['design_hash'],changed['design_hash'])

    def test_original_theme_color_option_keeps_classic_compatible(self):
        from backend.card_layout import normalize_options
        normalized,_=normalize_options({'global_style':{'accent':'default'}})
        self.assertEqual(normalized['global_style']['accent'],'default')
        run=fixture()
        original=preview_run(run, options={'global_style':{'accent':'default'}})
        green=preview_run(run, options={'global_style':{'accent':'green'}})
        self.assertEqual([p['data_url'] for p in original['pages']], [p['data_url'] for p in green['pages']])

    def test_global_style_validation_and_priority_over_legacy_page_settings(self):
        from backend.card_layout import normalize_options
        for style in (None,[],{'accent':[]},{'size':'tiny'},{'unknown':True}):
            with self.assertRaises(DomainError):normalize_options({'global_style':style})
        run=fixture('明确的资料内容。' * 30)
        a=preview_run(run,options={'global_style':{'accent':'blue'}})
        b=preview_run(run,options={'global_style':{'accent':'blue'},'page_styles':{'0':{'accent':'orange'}}})
        self.assertEqual([p['data_url'] for p in a['pages']],[p['data_url'] for p in b['pages']])

    def test_each_template_draws_all_content_without_rewriting(self):
        run = fixture('第一个要点：接口要匹配。\n\n第二个要点：电池续航因使用条件不同。' * 30)
        snapshot = confirmed_snapshot(run)
        content = snapshot['content']
        original = ImageDraw.ImageDraw.text
        for template in ('classic', 'checklist'):
            drawn = []
            def record(draw, xy, text, *args, **kwargs):
                if xy[0] == 112 or (xy[0] == 70 and xy[1] >= 270 and xy[1] < 1120):
                    drawn.append(text)
                return original(draw, xy, text, *args, **kwargs)
            with patch.object(ImageDraw.ImageDraw, 'text', record):
                render_images(snapshot, template)
            flattened = ''.join(drawn)
            for text in (content['selected_title'], content['body'], content['cta']):
                self.assertIn(text.replace('\n', ''), flattened)
            self.assertEqual(snapshot['content'], run.drafts[0]['content'])

    def test_wrapping_keeps_punctuation_with_previous_character(self):
        from PIL import ImageFont
        from backend.media_exports import wrap_text, font_path
        font = ImageFont.truetype(font_path(), 42)
        text = '选择接口匹配的鼠标。再看携带和电池。'
        lines = wrap_text(text, font, font.getlength('选择接口匹配的鼠标'))
        self.assertEqual(''.join(lines), text)
        self.assertTrue(all(not line.startswith('。') for line in lines))

    def test_unconfirmed_preview_and_invalid_template_rejected(self):
        run = fixture()
        for template in ('../unsafe', '', None, []):
            with self.assertRaises(DomainError): preview_run(run, template)
            with self.assertRaises(DomainError): export_run(run, template=template)
        run.run_status = 'RUNNING'
        with self.assertRaises(DomainError): preview_run(run)

    def test_page_limit_unchanged_for_both_templates(self):
        for template in ('classic', 'checklist'):
            with self.assertRaises(DomainError): preview_run(fixture('长' * 30000), template)

    def test_complete_video_uses_exact_selected_template_pages(self):
        run = fixture()
        expected = render_images(confirmed_snapshot(run), 'checklist')
        def video(snapshot, pages=None, template='classic'):
            self.assertEqual(template, 'checklist')
            self.assertEqual(pages, expected)
            snapshot['video'] = {'audio': False}
            return [('video.mp4', b'test-video')]
        with patch('backend.media_exports._video', side_effect=video):
            data, _, _ = export_run(run, 'complete', template='checklist')
        with zipfile.ZipFile(BytesIO(data)) as archive:
            for name, png in expected:
                self.assertEqual(archive.read('images/' + name), png)

    def test_standalone_video_passes_template_to_renderer(self):
        with patch('backend.media_exports.capabilities', return_value={'video_available': True}), patch('backend.media_exports.render_images', side_effect=DomainError('MEDIA_UNAVAILABLE', 'test')) as render:
            with self.assertRaises(DomainError): _video(confirmed_snapshot(fixture()), template='checklist')
            self.assertEqual(render.call_args.kwargs['template'], 'checklist')

    def test_paragraphs_words_and_punctuation_are_preserved(self):
        from PIL import ImageFont
        from backend.media_exports import font_path, wrap_text
        from backend.card_layout import paginate
        font = ImageFont.truetype(font_path(), 40)
        paragraphs = ['① 接口：支持 Windows、macOS、ChromeOS 和 Linux。' * 3,
                      '② 携带：小巧不等于每个人都握得舒服，是否合手仍要自己判断。' * 3,
                      '③ 供电：实际续航受条件影响。']
        pages = paginate('\n\n'.join(paragraphs), font)
        flattened = [block for page in pages for block in page]
        self.assertEqual(flattened, paragraphs)
        lines = wrap_text(paragraphs[0], font, 450)
        self.assertEqual(''.join(lines), paragraphs[0])
        self.assertEqual(sum(line.count('ChromeOS') for line in lines), 3)
        self.assertTrue(all(not line.startswith(('，', '。', '、')) for line in lines))

    def test_local_style_changes_only_selected_page_and_preserves_page_count(self):
        run = fixture(('① 核对接口和系统。' * 18) + '\n\n' + ('② 检查携带空间。' * 18))
        original = preview_run(run)
        changed = preview_run(run, options={'page_styles': {'1': {'size': 'large', 'accent': 'orange'}}})
        self.assertEqual(original['page_count'], changed['page_count'])
        for index, page in enumerate(original['pages']):
            self.assertEqual(page['sha256'] == changed['pages'][index]['sha256'], index != 1)
        self.assertNotEqual(original['design_hash'], changed['design_hash'])
        with self.assertRaises(DomainError): preview_run(run, options={'page_styles': {'23': {'size': 'large'}}})
        with self.assertRaises(DomainError): export_run(run, expected_design_hash=changed['design_hash'])

    def test_uploaded_photo_preview_export_match_without_base64_or_exif_in_manifest(self):
        source = BytesIO()
        im = Image.new('RGB', (600, 400), 'orange')
        exif = Image.Exif(); exif[270] = 'private-metadata'
        im.save(source, 'JPEG', exif=exif)
        uri = 'data:image/jpeg;base64,' + base64.b64encode(source.getvalue()).decode()
        options = {'cover_image': uri, 'page_styles': {'0': {'accent': 'blue'}}}
        preview = preview_run(fixture(), 'checklist', options)
        data, _, _ = export_run(fixture(), template='checklist', options=options, expected_design_hash=preview['design_hash'])
        with zipfile.ZipFile(BytesIO(data)) as archive:
            manifest = archive.read('manifest.json').decode()
            self.assertIn('image_sha256', manifest)
            self.assertNotIn(uri, manifest)
            self.assertNotIn('private-metadata', manifest)
            for page in preview['pages']:
                self.assertEqual(base64.b64decode(page['data_url'].split(',')[1]), archive.read(page['name']))
                self.assertFalse(Image.open(BytesIO(archive.read(page['name']))).getexif())

    def test_single_upload_is_only_on_cover_without_losing_body(self):
        source = BytesIO()
        Image.new('RGB', (600, 300), '#ed36c9').save(source, 'PNG')
        options = {'cover_image': 'data:image/png;base64,' + base64.b64encode(source.getvalue()).decode()}
        run = fixture('① 连接：先核对 USB 接口以及 ChromeOS 系统。\n\n'
                      '② 携带：外形小巧，是否合手需要自己判断。\n\n'
                      '③ 供电：官方标称最长12个月，实际受条件影响。' * 5)
        content = confirmed_snapshot(run)['content']
        original_text, original_paste = ImageDraw.ImageDraw.text, Image.Image.paste
        for template in ('classic', 'checklist'):
            drawn, placed, baselines = [], [], []
            def record_text(draw, xy, text, *args, **kwargs):
                if xy[0] == 112:
                    drawn.append(text); baselines.append(xy[1])
                return original_text(draw, xy, text, *args, **kwargs)
            def record_paste(image, photo, box=None, *args, **kwargs):
                if isinstance(photo, Image.Image):
                    placed.append((photo.size, box))
                return original_paste(image, photo, box, *args, **kwargs)
            with patch.object(ImageDraw.ImageDraw, 'text', record_text), patch.object(Image.Image, 'paste', record_paste):
                preview = preview_run(run, template, options)
            self.assertGreater(preview['page_count'], 2)
            self.assertEqual(len(placed), 1)
            self.assertTrue(all(w == 2 * h for (w, h), _ in placed))
            self.assertTrue(all(w <= 410 and h <= 260 for (w, h), _ in placed[1:]))
            self.assertTrue(all(240 <= y < 1270 for y in baselines))
            for value in (content['body'], content['cta']):
                self.assertIn(value.replace('\n', ''), ''.join(drawn))
            changed = preview_run(run, template, dict(options, page_styles={'1': {'size': 'large'}}))
            self.assertEqual(changed['page_count'], preview['page_count'])

    def test_product_photo_preference_is_validated_and_preserved(self):
        from backend.card_layout import normalize_options
        self.assertEqual(normalize_options({})[0]['product_photo'], 'auto')
        self.assertEqual(normalize_options({'product_photo': 'none'})[0]['product_photo'], 'none')
        for invalid in ('unknown', [], None):
            with self.assertRaises(DomainError):
                normalize_options({'product_photo': invalid})

    def test_single_photo_attribution_only_on_cover_but_not_user_upload(self):
        from backend.card_layout import compose
        from backend.media_exports import font_path
        source = BytesIO()
        Image.new('RGB', (100, 80), 'orange').save(source, 'PNG')
        options = {'cover_image': 'data:image/png;base64,' + base64.b64encode(source.getvalue()).decode()}
        snapshot = confirmed_snapshot(fixture())
        original = ImageDraw.ImageDraw.text
        for photo in (None, {'author': 'Hayden Schiff', 'license': 'CC BY 4.0'}):
            snapshot['product_photo'] = photo
            credits = []
            def record(draw, xy, text, *args, **kwargs):
                if xy[1] == 1390: credits.append(text)
                return original(draw, xy, text, *args, **kwargs)
            with patch.object(ImageDraw.ImageDraw, 'text', record):
                pages, _, _ = compose(snapshot, 'classic', font_path(), options)
            self.assertEqual(len(credits), 1 if photo else 0)
            if photo:
                self.assertTrue(all('Hayden Schiff / CC BY 4.0' in credit for credit in credits))

    def test_invalid_image_and_options_fail_cleanly(self):
        invalid = [{'cover_image': 'data:image/svg+xml;base64,AAAA'}, {'cover_image': 'data:image/png;base64,@@@@'},
                   {'cover_image': 'data:image/png;base64,' + base64.b64encode(b'not an image').decode()},
                   {'page_styles': {'0': {'size': 'huge'}}}, {'page_styles': {'-1': {}}}, {'untrusted': True}, {'page_styles': {'0': {'accent': []}}}, {'page_styles': {'0': {'size': {}}}}]
        for options in invalid:
            with self.subTest(options=str(options)[:70]), self.assertRaises(DomainError):
                preview_run(fixture(), options=options)

    def test_extremely_long_title_word_rejected_instead_of_clipped(self):
        snapshot = confirmed_snapshot(fixture())
        snapshot['content'] = dict(snapshot['content'], selected_title='A' * 400)
        with self.assertRaises(DomainError): render_images(snapshot)

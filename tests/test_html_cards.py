"""Real browser rendering acceptance for the vendored MIT themes (no model calls)."""
import base64
from io import BytesIO
import unittest
import zipfile
from unittest.mock import patch
from PIL import Image
from backend.html_cards import THEMES
from backend.media_exports import preview_run,export_run
from backend.contracts import DomainError
from backend.workflow import digest
from tests.test_media_exports import fixture


def product_run(body=None):
    run=fixture(body or ('① 连接：罗技M185通过USB接收器连接，请核对电脑接口。\n\n② 携带：机身小巧，适合随身携带。\n\n③ 供电：电池最长12个月，实际取决于使用条件。\n\n')*4)
    c=run.drafts[0]['content'];c['selected_title']='罗技M185：连接、携带、供电';c['cta']='你的电脑还有USB接口吗？'
    run.drafts[0]['content_hash']=run.acceptance['content_hash']=digest(c)
    return run


class HtmlCardTests(unittest.TestCase):
    def test_eight_themes_real_png_all_content_and_distinct_photos(self):
        outputs=[]
        for theme in THEMES:
            with self.subTest(theme=theme):
                run=product_run();preview=preview_run(run,theme)
                self.assertGreaterEqual(preview['page_count'],3)
                self.assertTrue(all(p['layout_verified'] for p in preview['pages']))
                self.assertEqual(len({p['photo_id'] for p in preview['pages'][:3]}),3)
                self.assertTrue(all(not p['photo_id'] for p in preview['pages'][3:]))
                blocks=''.join(''.join(p['text_blocks']) for p in preview['pages'])
                c=run.drafts[0]['content']
                for paragraph in c['body'].split('\n\n'):
                    self.assertIn(paragraph,blocks)
                self.assertIn(c['cta'],blocks)
                png=base64.b64decode(preview['pages'][0]['data_url'].split(',')[1]);outputs.append(png)
                self.assertEqual(Image.open(BytesIO(png)).size,(1080,1440))
        self.assertEqual(len(set(outputs)),8)

    def test_export_pixels_equal_preview_and_colors_change_every_page(self):
        run=product_run()
        original=preview_run(run,'xhs-e')
        options={'global_style':{'size':'large','accent':'orange'}}
        preview=preview_run(run,'xhs-e',options)
        data,_,_=export_run(run,'images',template='xhs-e',options=options,expected_design_hash=preview['design_hash'])
        with zipfile.ZipFile(BytesIO(data)) as z:
            for page in preview['pages']:
                self.assertEqual(z.read(page['name']),base64.b64decode(page['data_url'].split(',')[1]))
        self.assertNotEqual(original['design_hash'],preview['design_hash'])
        for before,after in zip(original['pages'],preview['pages']):self.assertNotEqual(before['sha256'],after['sha256'])

    def test_color_alone_changes_every_page_and_cover_title_for_all_themes(self):
        # Identical font size/content: changed pixels must come from accent styling.
        for theme in THEMES:
            with self.subTest(theme=theme):
                run=product_run()
                original=preview_run(run,theme,{'global_style':{'size':'normal','accent':'default'}})
                changed=preview_run(run,theme,{'global_style':{'size':'normal','accent':'blue'}})
                self.assertEqual(original['page_count'],changed['page_count'])
                for before,after in zip(original['pages'],changed['pages']):
                    self.assertEqual(before['text_blocks'],after['text_blocks'])
                    self.assertNotEqual(before['sha256'],after['sha256'])
                def cover_crop(preview):
                    raw=base64.b64decode(preview['pages'][0]['data_url'].split(',')[1])
                    # Excludes tiny header and footer: ensure a clearly visible title change.
                    return Image.open(BytesIO(raw)).crop((88,160,990,1080)).tobytes()
                self.assertNotEqual(cover_crop(original),cover_crop(changed))

    def test_real_length_draft_tags_use_last_page_footer_not_a_separate_card(self):
        body=('带笔记本从教室到图书馆，鼠标塞进包就走的场景里，选之前先按连接、携带、供电三步核对。以罗技 M185 为例：'
              '① 连接——它用 USB 接收器即插即用，买前先确认电脑有可用 USB 接口，再核对系统，官方列出 Windows、macOS、ChromeOS 和 Linux，都对得上这步才算过。'
              '② 携带——官方说外形紧凑、左右手均可用，适合随身包；但紧凑不等于适合你的手型，握持舒不舒服要自己上手判断，这点只能你自己定。'
              '③ 供电——它带电源开关和自动休眠，官方标称电池最长可用 12 个月，实际时长随使用方式和条件变化，别按满一年来预期。'
              '三步都对得上，可以把它列入候选；价格、按键声音、竞品对比暂无资料，不代为判断。\\n资料来源：罗技官网')
        run=product_run(body);c=run.drafts[0]['content']
        c['selected_title']='罗技M185适不适合你？三步自查再说'
        c['tags']=['大学生鼠标','无线鼠标','笔记本配件','选购思路','罗技M185']
        run.drafts[0]['content_hash']=run.acceptance['content_hash']=digest(c)
        for theme in ('xhs-a','xhs-e','xhs-f'):
            with self.subTest(theme=theme):
                preview=preview_run(run,theme)
                self.assertEqual(preview['page_count'],3)
                self.assertEqual(preview['pages'][-1]['tags'],' '.join('#'+tag for tag in c['tags']))
                self.assertTrue(all(p['text_blocks'] for p in preview['pages'][1:]))
                self.assertTrue(all(p['layout_verified'] for p in preview['pages']))
                self.assertEqual(''.join(''.join(p['text_blocks']) for p in preview['pages']),body+c['cta'])

    def test_untrusted_markup_and_long_words_are_visible_text(self):
        text='<script>fetch("https://example.com/secret")</script> '+('abcdef'*100)+'。中文句子完整保留。'
        preview=preview_run(product_run(text),'xhs-g')
        blocks=''.join(''.join(p['text_blocks']) for p in preview['pages'])
        self.assertIn(text,blocks)
        self.assertTrue(all(p['layout_verified'] for p in preview['pages']))

    def test_title_500_never_silently_clips(self):
        run=product_run();c=run.drafts[0]['content'];c['selected_title']='罗技M185'+ '接口与供电'*98+'选择鼠标'
        run.drafts[0]['content_hash']=run.acceptance['content_hash']=digest(c)
        try:
            preview=preview_run(run,'xhs-f')
            self.assertTrue(all(p['layout_verified'] for p in preview['pages']))
        except DomainError as e:
            self.assertEqual(e.code,'INVALID_INPUT')

    def test_html_renderer_failure_never_exports_package_without_images(self):
        with patch('backend.html_cards.compose',side_effect=DomainError('MEDIA_UNAVAILABLE','browser missing')):
            with self.assertRaises(DomainError):export_run(product_run(),'complete',template='xhs-e')

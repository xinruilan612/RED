import base64
from io import BytesIO
import json
import unittest
from unittest.mock import patch
from PIL import Image
from backend import poster_local as p
from backend.contracts import DomainError


class LocalPosterTests(unittest.TestCase):
    def setUp(self):
        b=BytesIO();Image.new('RGB',(220,140),'#627d62').save(b,format='PNG')
        self.source='data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()
        self.snapshot={'content':{'selected_title':'我的日常伴侣','body':'保留  两个空格。\n第二行原文：不改写。','cta':'你会如何选择？'}}

    def decode(self,value):return Image.open(BytesIO(base64.b64decode(value.split(',',1)[1])))

    def test_dimensions_and_exact_confirmed_text(self):
        with patch.object(p,'_draw_lines',wraps=p._draw_lines) as drawing:
            image=self.decode(p.render(self.source,self.snapshot,'纸感'))
        self.assertEqual(image.size,(1080,1800))
        self.assertEqual(json.loads(image.info['youji_confirmed_text']),self.snapshot['content'])
        self.assertEqual(drawing.call_args_list[0].args[2],['我的日常伴侣'])
        self.assertEqual(drawing.call_args_list[1].args[2],['保留  两个空格。','第二行原文：不改写。','','你会如何选择？'])

    def test_styles_differ_and_are_deterministic(self):
        images=[p.render(self.source,self.snapshot,'',style) for style in p.STYLES]
        self.assertEqual(len(set(images)),3)
        self.assertEqual(images[0],p.render(self.source,self.snapshot,'','zine'))

    def test_invalid_source_and_style(self):
        for source,style in [('invalid','zine'),(self.source,'unknown')]:
            with self.assertRaises(DomainError):p.render(source,self.snapshot,'',style)

    def test_no_text_truncation_on_overflow(self):
        self.snapshot['content']['body']='内容'*2900
        with self.assertRaises(DomainError) as e:p.render(self.source,self.snapshot,'')
        self.assertEqual(e.exception.code,'INVALID_INPUT')

    def test_snapshot_is_not_mutated(self):
        original=json.dumps(self.snapshot,ensure_ascii=False)
        p.render(self.source,self.snapshot,'蓝色，增加留白')
        self.assertEqual(json.dumps(self.snapshot,ensure_ascii=False),original)

    def test_wrap_preserves_every_character(self):
        text='  原文 A B标点，不能删除   '
        self.assertEqual(''.join(p._wrap(text,p._font(30),100)),text)

    def test_brief_changes_visible_controls(self):
        base=p.render(self.source,self.snapshot,'')
        self.assertNotEqual(base,p.render(self.source,self.snapshot,'红色，白色背景，增加留白'))
        self.assertEqual(p.brief_options('红色，白色背景')['accent'],'#a74c37')
        with self.assertRaises(DomainError):p.render(self.source,self.snapshot,'把鼠标变成猫')

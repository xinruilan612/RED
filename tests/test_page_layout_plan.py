"""Verify layout-only plans never mutate accepted copy or product identity."""
import base64
from copy import deepcopy
from io import BytesIO
import re
import unittest
import zipfile
from backend.card_layout import normalize_options
from backend.contracts import DomainError
from backend.media_exports import preview_run, export_run
from tests.test_html_cards import product_run


class PageLayoutPlanTests(unittest.TestCase):
    def setUp(self):
        self.run=product_run('第一步先核对罗技M185的USB接收器连接方式。确认电脑是否有合适的接口。'*5+'\n\n'+'第二步再看携带和供电。机身小巧，电池表现取决于使用条件。'*4)

    @staticmethod
    def plan(preview):
        return {'pages':[{'text_blocks':list(row['text_blocks']), 'photo_index':row['photo_index']} for row in preview['pages']]}

    def test_split_one_page_preserves_all_copy_other_pages_and_photos_export(self):
        before=preview_run(self.run,'xhs-a')
        self.assertEqual(before['page_count'],3)
        plan=self.plan(before)
        old=plan['pages'][1]
        text=''.join(old['text_blocks'])
        sentences=re.findall(r'.*?[。！？；]|.+$',text,re.S)
        mid=max(1,len(sentences)//2)
        first,second=''.join(sentences[:mid]),''.join(sentences[mid:])
        self.assertTrue(second)
        plan['pages'][1:2]=[{'text_blocks':[first],'photo_index':old['photo_index']},{'text_blocks':[second],'photo_index':None}]
        options={'layout_plan':plan}
        after=preview_run(self.run,'xhs-a',options)
        self.assertEqual(after['page_count'],4)
        self.assertNotEqual(before['design_hash'],after['design_hash'])
        compact=lambda p:re.sub(r'\s+','',''.join(''.join(row['text_blocks']) for row in p['pages']))
        self.assertEqual(compact(before),compact(after))
        self.assertEqual(before['pages'][2]['text_blocks'],after['pages'][3]['text_blocks'])
        self.assertEqual(before['pages'][2]['photo_id'],after['pages'][3]['photo_id'])
        self.assertEqual(before['pages'][1]['photo_id'],after['pages'][1]['photo_id'])
        self.assertIsNone(after['pages'][2]['photo_id'])
        self.assertTrue(all(row['layout_verified'] for row in after['pages']))
        data,_,_=export_run(self.run,'images',template='xhs-a',options=options,expected_design_hash=after['design_hash'])
        with zipfile.ZipFile(BytesIO(data)) as z:
            for row in after['pages']:self.assertEqual(z.read(row['name']),base64.b64decode(row['data_url'].split(',')[1]))

    def test_forged_missing_duplicate_and_unavailable_image_rejected(self):
        initial=self.plan(preview_run(self.run,'xhs-e'))
        plans=[]
        p=deepcopy(initial);p['pages'][1]['text_blocks'][0]+='伪造卖点';plans.append(p)
        p=deepcopy(initial);p['pages'][1]['text_blocks'][0]=p['pages'][1]['text_blocks'][0][1:];plans.append(p)
        p=deepcopy(initial);p['pages'][1]['photo_index']=0;plans.append(p)
        p=deepcopy(initial);p['pages'][1]['photo_index']=23;plans.append(p)
        for plan in plans:
            with self.subTest(plan=plan),self.assertRaises(DomainError):preview_run(self.run,'xhs-e',{'layout_plan':plan})

    def test_plan_does_not_silently_repaginates_overflow(self):
        run=product_run('罗技M185必须保持完整的确认文案。'*90)
        c=run.drafts[0]['content']
        plan={'pages':[{'text_blocks':[],'photo_index':0},{'text_blocks':[c['body'],c['cta']],'photo_index':1}]}
        with self.assertRaisesRegex(DomainError,'放不下完整文字'):preview_run(run,'xhs-a',{'layout_plan':plan})

    def test_strict_plan_structure_and_size(self):
        valid={'pages':[{'text_blocks':[],'photo_index':0},{'text_blocks':['正文'],'photo_index':None}]}
        bad=[None,[],{}, {'pages':[]}, {'pages':valid['pages'],'extra':True}]
        for value in (True,-1,24,'0',1.1):
            p=deepcopy(valid);p['pages'][1]['photo_index']=value;bad.append(p)
        for value in (None,'正文',[''],[3]):
            p=deepcopy(valid);p['pages'][1]['text_blocks']=value;bad.append(p)
        p=deepcopy(valid);p['pages'][0]['photo_index']=1;bad.append(p)
        p=deepcopy(valid);p['pages'][0]['text_blocks']=['封面不可写正文'];bad.append(p)
        p=deepcopy(valid);p['pages'][1]['text_blocks']=['字'*30001];bad.append(p)
        p=deepcopy(valid);p['pages']+=deepcopy(p['pages'][1:])*24;bad.append(p)
        for plan in bad:
            with self.subTest(plan=str(plan)[:80]),self.assertRaises(DomainError):normalize_options({'layout_plan':plan})
        self.assertEqual(normalize_options({'layout_plan':valid})[0]['layout_plan'],valid)

    def test_centered_points_and_photo_order_are_measured_and_exported(self):
        run=product_run('开场说明。① 连接：先核对接口。② 携带：先核对空间。')
        before=preview_run(run,'xhs-a')
        row=before['pages'][1]
        self.assertTrue(any(t.startswith('①') for t in row['text_blocks']))
        self.assertTrue(any(t.startswith('②') for t in row['text_blocks']))
        g=row['layout_geometry']
        self.assertEqual(g['align'],'center')
        self.assertLess(g['image']['bottom'],g['text']['top'])
        plan=self.plan(before);plan['pages'][1].update(photo_position='below',text_align='left')
        after=preview_run(run,'xhs-a',{'layout_plan':plan})
        g=after['pages'][1]['layout_geometry']
        self.assertGreater(g['image']['top'],g['text']['bottom'])
        self.assertEqual(g['align'],'left')
        self.assertEqual(after['pages'][1]['text_blocks'],row['text_blocks'])
        # Content block is vertically balanced beneath the fixed subtitle.
        top=g['text']['top'];bottom=g['height']-g['image']['bottom']
        self.assertLess(abs(top-bottom),110)
        data,_,_=export_run(run,'images',template='xhs-a',options={'layout_plan':plan},expected_design_hash=after['design_hash'])
        with zipfile.ZipFile(BytesIO(data)) as z:
            for p in after['pages']:self.assertEqual(z.read(p['name']),base64.b64decode(p['data_url'].split(',')[1]))

    def test_invalid_alignment_and_photo_position_rejected(self):
        for key,value in [('photo_position','sideways'),('text_align','justify'),('text_align',True)]:
            plan={'pages':[{'text_blocks':[],'photo_index':0},{'text_blocks':['正文'],'photo_index':None,key:value}]}
            with self.assertRaises(DomainError):normalize_options({'layout_plan':plan})

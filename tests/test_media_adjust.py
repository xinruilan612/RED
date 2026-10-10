import unittest
from backend.media_adjust import split_blocks
from backend.contracts import DomainError

class SplitBlocksTests(unittest.TestCase):
    def test_split_preserves_exact_characters_and_readable_boundaries(self):
        blocks=['第一句。第二句比较长一些。','第三句。第四句！']
        left,right=split_blocks(blocks)
        self.assertEqual(''.join(left+right),''.join(blocks))
        self.assertTrue(left and right)
        self.assertIn(left[-1][-1],'。！')
    def test_numbered_points_stay_together_even_when_sentence_cut_is_closer(self):
        blocks=['导语。①连接：第一句很长。连接补充。②携带：短。③供电：短。']
        left,right=split_blocks(blocks)
        self.assertEqual(''.join(left+right),''.join(blocks))
        self.assertTrue(right[0].startswith(('②','③')))
        self.assertIn('连接补充。',''.join(left))

    def test_no_sentence_boundary_is_explained(self):
        with self.assertRaises(DomainError):split_blocks(['不能切开的单句'])
    def test_paragraph_boundary_keeps_english_words(self):
        left,right=split_blocks(['first paragraph','next paragraph'])
        self.assertEqual(left,['first paragraph']);self.assertEqual(right,['next paragraph'])

class LayoutCommandTests(unittest.TestCase):
    def proposal(self,action,index=1,photo=1):
        from unittest.mock import patch
        from backend.media_adjust import propose
        before={'pages':[{'text_blocks':[],'photo_index':0},{'text_blocks':['第一句。第二句。第三句。第四句。'],'photo_index':photo},{'text_blocks':['其他页。'],'photo_index':None}]}
        data={'template':'xhs-d','page_index':index,'options':{'layout_plan':{'pages':[{'photo_position':'above','text_align':'center'},{'photo_position':'below','text_align':'left'},{'photo_position':'above','text_align':'left'}]}}}
        with patch('backend.media_exports.preview_run',return_value={'pages':[]}) as render:
            result=propose(object(),data,before,{'action':action})
        return result,render

    def test_photo_commands_preserve_text_and_other_page_settings(self):
        for action,position in [('photo_below','below'),('photo_above','above')]:
            result,_=self.proposal(action)
            pages=result['options']['layout_plan']['pages']
            self.assertEqual(pages[1]['photo_position'],position)
            self.assertEqual(pages[1]['text_align'],'left')
            self.assertEqual(pages[1]['text_blocks'],['第一句。第二句。第三句。第四句。'])
            self.assertEqual(pages[2]['text_align'],'left')
            self.assertEqual(result['after_page_indices'],[1])

    def test_alignment_commands_do_not_rewrite_or_relocate_photo(self):
        for action,alignment in [('center_points','center'),('align_left','left')]:
            result,_=self.proposal(action)
            page=result['options']['layout_plan']['pages'][1]
            self.assertEqual(page['text_align'],alignment)
            self.assertEqual(page['photo_position'],'below')
            self.assertEqual(page['photo_index'],1)
            self.assertEqual(page['text_blocks'],['第一句。第二句。第三句。第四句。'])

    def test_split_inherits_existing_layout_settings(self):
        result,_=self.proposal('split')
        pages=result['options']['layout_plan']['pages']
        for page in pages[1:3]:
            self.assertEqual(page['text_align'],'left')
            self.assertEqual(page['photo_position'],'below')
        self.assertEqual(pages[1]['photo_index'],1)
        self.assertIsNone(pages[2]['photo_index'])
        self.assertEqual(''.join(pages[1]['text_blocks']+pages[2]['text_blocks']),'第一句。第二句。第三句。第四句。')

    def test_unsupported_and_invalid_targets_fail_without_rendering(self):
        for action,index,photo in [('unsupported',1,1),('photo_below',1,None),('photo_above',1,None),('center_points',0,0),('align_left',0,0),('photo_below',0,0)]:
            with self.subTest(action=action,index=index,photo=photo),self.assertRaises(DomainError):
                self.proposal(action,index,photo)

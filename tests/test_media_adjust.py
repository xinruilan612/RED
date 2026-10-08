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
    def test_no_sentence_boundary_is_explained(self):
        with self.assertRaises(DomainError):split_blocks(['不能切开的单句'])
    def test_paragraph_boundary_keeps_english_words(self):
        left,right=split_blocks(['first paragraph','next paragraph'])
        self.assertEqual(left,['first paragraph']);self.assertEqual(right,['next paragraph'])

"""Source formatting repair must not manufacture source attribution."""
import copy
import unittest
from backend.citation_ids import repair

class CitationIdTests(unittest.TestCase):
    def test_hyphen_only_unique_exact_quote_and_raw_preserved(self):
        raw={'observations':[{'source_id':'kb:abc-def123','quote':'确切原文','interpretation':'观察'}]}
        before=copy.deepcopy(raw)
        fixed,changes=repair('audience',raw,[{'source_id':'kb:abcdef-123','text':'前文确切原文后文'}])
        self.assertEqual(fixed['observations'][0]['source_id'],'kb:abcdef-123')
        self.assertEqual(raw,before)
        self.assertEqual(changes[0]['from'],'kb:abc-def123')
        self.assertEqual(changes[0]['quote'],'确切原文')

    def test_no_repair_for_different_id_quote_namespace_or_ambiguity(self):
        raw={'facts':[{'source_id':'kb:abc-def123','quote':'确切原文'}]}
        cases=[ [{'source_id':'kb:other','text':'确切原文'}],
                [{'source_id':'web:abcdef123','text':'确切原文'}],
                [{'source_id':'kb:abcdef123','text':'别的文字'}],
                [{'source_id':'kb:abcdef123','text':'确切原文'},{'source_id':'kb:ab-cdef123','text':'确切原文'}],
                [{'source_id':'kb:abc-def123','text':'别的文字'},{'source_id':'kb:abcdef123','text':'确切原文'}]]
        for sources in cases:
            with self.subTest(sources=sources):
                fixed,changes=repair('research',raw,sources)
                self.assertEqual(fixed,raw);self.assertFalse(changes)

    def test_review_and_malformed_output_untouched(self):
        for stage,raw in [('review',{'claim_map':[{'source_id':'kb:abc-def','quote':'原文'}]}),('audience',{'observations':[None,{}]}),('research',None)]:
            self.assertEqual(repair(stage,raw,[{'source_id':'kb:abcdef','text':'原文'}]),(raw,[]))

    def test_review_only_trims_outer_whitespace_of_exact_bound_quote(self):
        raw={'decision':'revision_required','claim_map':[{'source_id':'s','quote':' 逐字原文\n','excerpt':'当前稿件'}]}
        fixed,changes=repair('review',raw,[{'source_id':'s','text':'逐字原文'}])
        self.assertEqual(fixed['decision'],'revision_required')
        self.assertEqual(fixed['claim_map'][0]['quote'],'逐字原文')
        self.assertEqual(raw['claim_map'][0]['quote'],' 逐字原文\n')
        self.assertEqual(changes[0]['reason'],'quote_outer_whitespace')
        raw['claim_map'][0]['quote']='逐 字原文'
        self.assertEqual(repair('review',raw,[{'source_id':'s','text':'逐字原文'}]),(raw,[]))

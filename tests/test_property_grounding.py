"""Regression coverage for limited, local property evidence guards."""
import unittest
from backend.factual_grounding import annotate_review, findings


class PropertyGroundingTests(unittest.TestCase):
    def check(self, body, quote=None, *, tags=None):
        content={'body':body, 'tags':tags or []}
        sources=[{'source_id':'source', 'text':quote}] if quote is not None else []
        mapping=[{'source_id':'source', 'excerpt':body, 'quote':quote}] if quote is not None else []
        # Every fixture satisfies the upstream literal citation contract.
        for item in mapping:
            self.assertIn(item['quote'], sources[0]['text'])
            self.assertIn(item['excerpt'], content['body'])
        report={'decision':'approved','next_action':'await_user_confirmation',
                'claim_map':mapping,'issues':[],'previous_issue_results':[],
                'checks':[{'name':'evidence_integrity','result':'pass'}],
                'human_questions':[],'limitations':[]}
        return annotate_review(report,content,sources,{}),findings(content,mapping,sources,{})

    def test_invalid_support_is_handed_to_human(self):
        cases=[
            ('这台电脑绝不卡顿。','这台电脑完全够用。'),
            ('鼠标即插即用。','该鼠标不是即插即用，需要手动安装驱动。'),
            ('鼠标即插即用。','仅在Windows系统上即插即用，其他系统需要安装驱动。'),
            ('价格尚未确认，但鼠标即插即用。',None),
            ('价格尚未确认但鼠标即插即用。',None),
            ('鼠标握感舒适，长时间使用不累。','鼠标握感舒适。'),
            ('鼠标即插即用。','如果先安装驱动，鼠标即插即用。'),
            ('鼠标即插即用。','鼠标并非即插即用。'),
            ('鼠标即插即用。','鼠标即插即用仅限Windows。'),
        ]
        for body,quote in cases:
            with self.subTest(body=body,quote=quote):
                report,issues=self.check(body,quote)
                self.assertTrue(issues)
                self.assertEqual(report['decision'],'needs_human')
                self.assertEqual(report['checks'][0]['result'],'fail')

    def test_tags_are_independent(self):
        report,issues=self.check('',tags=['价格尚未确认','即插即用'])
        self.assertEqual(report['decision'],'needs_human')
        self.assertEqual([(i['location'],i['excerpt']) for i in issues],[('tags','即插即用')])

    def test_matching_conditions_and_true_synonyms_pass(self):
        cases=[
            ('产品插上就能用。','产品即插即用。'),
            ('产品无需安装驱动。','产品无需下载任何驱动。'),
            ('鼠标握持舒服。','鼠标握感舒适。'),
            ('仅在Windows系统上即插即用。','仅在Windows系统上插上就能用。'),
            ('如果先安装驱动，鼠标即插即用。','如果先安装驱动，鼠标插上就能用。'),
            ('鼠标握感舒适，长时间使用不累。','鼠标握持舒服，久用不累。'),
        ]
        for body,quote in cases:
            with self.subTest(body=body,quote=quote):
                report,issues=self.check(body,quote)
                self.assertEqual(issues,[])
                self.assertEqual(report['decision'],'approved')

    def test_different_condition_is_not_equivalent(self):
        report,_=self.check('仅在Linux系统上即插即用。','仅在Windows系统上即插即用。')
        self.assertEqual(report['decision'],'needs_human')

    def test_uncertainty_applies_to_its_clause_only(self):
        for body in ('是否即插即用，请购买前确认。','握感舒适与否建议到店体验。',
                     '没有实测记录，不能保证即插即用。'):
            with self.subTest(body=body):
                self.assertEqual(self.check(body)[1],[])
        self.assertTrue(self.check('是否即插即用尚未确认；但握感舒适。')[1])

    def test_citation_must_cover_each_occurrence(self):
        body='鼠标握感舒适，但键盘握感舒适。'
        source={'source_id':'s','text':'鼠标握感舒适'}
        mapping=[{'source_id':'s','excerpt':'鼠标握感舒适','quote':source['text']}]
        self.assertTrue(findings({'body':body},mapping,[source],{}))

    def test_truncated_quote_cannot_remove_source_negation_or_condition(self):
        for text in ('鼠标不是即插即用。','仅在Windows系统上即插即用。',
                     '在Windows系统下即插即用。'):
            with self.subTest(text=text):
                source={'source_id':'s','text':text}
                mapping=[{'source_id':'s','excerpt':'即插即用','quote':'即插即用'}]
                self.assertTrue(findings({'body':'鼠标即插即用。'},mapping,[source],{}))

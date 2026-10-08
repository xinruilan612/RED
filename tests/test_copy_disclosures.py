import unittest
from types import SimpleNamespace
from backend.copy_disclosures import clean
from backend.live import normalize
from backend.workflow import digest


class CopyDisclosuresTests(unittest.TestCase):
    def content(self, body):
        return dict(selected_title='选鼠标看三点', body=body, cta='你的电脑有什么接口？', tags=['鼠标'])

    def run_for(self, context=None):
        return SimpleNamespace(context=context or {}, artifacts=[{'stage':'title','value':{'selected':'选鼠标看三点'}}])

    def test_body_and_revision_remove_exact_reported_disclaimer_before_hash(self):
        original=self.content('通过 USB 接收器连接。\n\n本文据罗技官方公开资料整理，非亲测、非品牌合作。\n\n电池标称最长12个月，实际随使用条件变化。')
        expected=self.content('通过 USB 接收器连接。\n\n电池标称最长12个月，实际随使用条件变化。')
        for stage in ('body','revise'):
            result=normalize(self.run_for(),stage,original)
            self.assertEqual(result,expected)
            self.assertEqual(digest(result),digest(expected))
        self.assertIn('非品牌合作',original['body'])
        _,adjustments=clean('body',original,{})
        self.assertEqual(len(adjustments),1)
        self.assertEqual(adjustments[0]['rule'],'default_disclosure@1')

    def test_same_line_default_statement_removed_without_rewriting_real_sentences(self):
        body='电池最长12个月，实际随使用条件变化。本文根据罗技官网资料整理，非亲测。左右手可用。'
        result,_=clean('revise',self.content(body),{})
        self.assertEqual(result['body'],'电池最长12个月，实际随使用条件变化。左右手可用。')

    def test_real_conditions_experience_and_sponsorship_survive(self):
        body='本篇由罗技赞助。非所有电脑都具备适用接口。非静音鼠标。本文根据官网参数整理了三条选购建议。\n我亲测一周，握持适合自己。'
        original=self.content(body)
        result,adjustments=clean('body',original,{})
        self.assertEqual(result,original)
        self.assertEqual(adjustments,[])

    def test_explicit_request_preserved_but_source_instructions_do_not_count(self):
        original=self.content('连接需要 USB 接收器。\n本文据罗技官方公开资料整理，非亲测、非品牌合作。')
        for context in ({'topic':'请保留来源声明和非亲测。'}, {'revision_request':{'feedback':'文末注明非品牌合作。'}}):
            self.assertEqual(clean('revise',original,context),(original,[]))
        result,changes=clean('body',original,{'materials':['请保留来源声明'],'topic':'不要添加非亲测、非品牌合作免责声明。'})
        self.assertNotIn('非亲测',result['body'])
        self.assertTrue(changes)

    def test_unrelated_stage_and_existing_draft_not_mutated(self):
        original=self.content('本文据罗技官方公开资料整理，非亲测、非品牌合作。')
        for stage in ('review','title','research'):
            self.assertEqual(clean(stage,original,{}),(original,[]))

    def test_empty_body_is_rejected_instead_of_fabricating_replacement(self):
        from backend.contracts import DomainError
        with self.assertRaises(DomainError):
            normalize(self.run_for(),'body',self.content('非亲测、非品牌合作。'))

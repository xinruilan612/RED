"""Publication copy is judged by the agents, never silently word-filtered."""
import unittest
from types import SimpleNamespace
from backend.live import normalize
from backend.workflow import digest

class CopyDisclosuresTests(unittest.TestCase):
    def test_body_and_revision_preserve_model_text_for_review(self):
        run=SimpleNamespace(context={},artifacts=[{'stage':'title','value':{'selected':'选鼠标看三点'}}])
        examples=[
            '本文据罗技官方公开资料整理，非亲测、非品牌合作。',
            '资料来源：罗技官网。',
            '我亲测一周，握持适合自己。',
            '本篇由罗技赞助。',
            '电池标称最长12个月，实际随使用条件变化。',
            '电池标称最长12个月。非亲测。左右手可用。',
        ]
        for stage in ('body','revise'):
            for body in examples:
                with self.subTest(stage=stage,body=body):
                    value=dict(selected_title='选鼠标看三点',body=body,cta='你的电脑有什么接口？',tags=['鼠标'])
                    result=normalize(run,stage,value)
                    self.assertEqual(result,value)
                    self.assertEqual(digest(result),digest(value))

    def test_empty_body_still_rejected_by_structure_validation(self):
        from backend.contracts import DomainError
        run=SimpleNamespace(context={},artifacts=[])
        with self.assertRaises(DomainError):
            normalize(run,'revise',dict(selected_title='标题',body='',cta='问题',tags=['鼠标']))

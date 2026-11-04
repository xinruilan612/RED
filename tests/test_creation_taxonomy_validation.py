"""Validation failures identify a field, a constraint, and a correction."""
import unittest
from backend.contracts import DomainError
from backend.creation_taxonomy import classify_document, classify_task, taxonomy


class CreationTaxonomyValidationTests(unittest.TestCase):
    def rejected(self, payload, *messages, document=False):
        with self.assertRaises(DomainError) as caught:
            if document:
                classify_document(payload, '标题', '正文')
            else:
                classify_task(payload)
        self.assertEqual(caught.exception.code, 'INVALID_INPUT')
        for message in messages:
            self.assertIn(message, str(caught.exception))

    def test_invalid_domain_values_have_specific_recovery(self):
        self.rejected({'domains': 'beauty'}, '领域格式', '勾选', '8')
        self.rejected({'domains': [None]}, '格式不正确', '重新选择')
        self.rejected({'domains': ['护肤']}, '护肤', '可选分类', '美妆', '重新选择')
        self.rejected({'domains': list(taxonomy()['domains'])[:9]}, '当前提交了 9 项', '取消多余')

    def test_eight_domains_are_accepted_and_unknown_values_never_mapped(self):
        choices = list(taxonomy()['domains'])[:8]
        self.assertEqual(classify_task({'domains': choices})['domains'], choices)
        self.assertEqual(classify_task({'domains': ['beauty', 'beauty']})['domains'], ['beauty'])
        self.rejected({'domains': ['美妆']}, '不在可选分类')

    def test_channel_and_format_reject_unhashable_values_with_domain_error(self):
        self.rejected({'channel': ['xiaohongshu']}, '渠道', '重新选择', '小红书')
        self.rejected({'format': {'value': 'note'}}, '内容形式', '图文笔记')
        self.rejected({'channel': 'any'}, '渠道')
        self.assertEqual(classify_document({'material_type': 'method', 'channel': 'any', 'format': 'any'}, '', '')['channel'], 'any')

    def test_word_count_and_goal_errors_are_actionable(self):
        for value in (True, '500字', 500.5, None):
            self.rejected({'word_count': value}, '目标字数', '整数')
        self.rejected({'word_count': 19}, '当前为 19', '20 至 10000', '修改')
        self.rejected({'word_count': 10001}, '当前为 10001')
        for value in (20, 10000):
            self.assertEqual(classify_task({'word_count': value})['word_count'], value)
        self.rejected({'goal': []}, '创作目标', '填写文字')
        self.rejected({'goal': '字' * 301}, '当前为 301 字', '删减')
        self.assertEqual(len(classify_task({'goal': '字' * 300})['goal']), 300)

    def test_document_purpose_and_required_domains_have_recovery(self):
        self.rejected({}, '资料用途', '请选择', document=True)
        for kind in ('fact', 'example'):
            self.rejected({'material_type': kind}, '至少需要选择 1 个领域', '勾选', document=True)
        self.assertEqual(classify_document({'material_type': 'method'}, '', '')['domains'], [])

    def test_falsey_non_objects_are_not_silently_accepted(self):
        for value in ([], '', False, 0):
            self.rejected(value, '分类信息格式不正确', '重新选择')
        self.assertEqual(classify_task(None)['domains'], ['general'])


if __name__ == '__main__':
    unittest.main()

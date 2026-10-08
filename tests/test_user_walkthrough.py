"""Keep the user walkthrough connected to real UI actions and safe boundaries."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / 'docs/USER_WALKTHROUGH.md'


class UserWalkthroughTests(unittest.TestCase):
    def test_local_document_links_resolve(self):
        text = GUIDE.read_text()
        for target in re.findall(r'\]\(([^)]+)\)', text):
            if target.startswith(('http://', 'https://', '#')):
                continue
            self.assertTrue((GUIDE.parent / target.split('#')[0]).is_file(), target)

    def test_core_tutorial_actions_exist_in_the_real_ui(self):
        text = GUIDE.read_text()
        ui = '\n'.join((ROOT / path).read_text() for path in (
            'frontend/index.html', 'frontend/app.js', 'frontend/knowledge.js',
            'frontend/account.js', 'frontend/media_exports.js'))
        for action in ('保存档案', '保存资料', '查看原文', '用这份资料创作',
                       '查找原文', '生成稿件并审核',
                       '这一次想怎么改？', '让 AI 按意见改稿并复审',
                       '我来修改文案', '保存为新版本（不调用 AI）',
                       '图卡预览与下载', '预览图卡',
                       '下载全部成品包'):
            with self.subTest(action=action):
                self.assertIn(action, text)
                self.assertIn(action, ui)

    def test_tutorial_matches_single_submit_and_bundle_flow(self):
        for path in (GUIDE, ROOT / 'docs/tutorials/skadis/00-先看这里-手把手教程.txt'):
            text = path.read_text()
            for action in ('生成稿件并审核', '让 AI 按意见改稿并复审',
                           '确认第 N 版', '知晓问题，人工采用第 N 版',
                           '预览图卡', '下载全部成品包', '重试并继续到审核'):
                self.assertIn(action, text)
            for obsolete in ('保存需求，开始创作', '下载图文包', '下载分镜与字幕',
                             '重试未完成步骤', '点“连续运行到人工处理”'):
                self.assertNotIn(obsolete, text)
            self.assertLess(text.index('预览图卡'), text.index('唯一的“下载全部成品包”'))
            self.assertIn('再次失败会停止', text)

    def test_creation_tutorial_does_not_require_removed_fee_confirmation(self):
        for path in (GUIDE, ROOT / 'docs/tutorials/skadis/00-先看这里-手把手教程.txt'):
            text = path.read_text()
            self.assertNotIn('同意费用并开始本次执行', text)
            self.assertIn('不再弹出费用确认', text)
            self.assertIn('预算上限', text)
        self.assertNotIn('执行前确认费用', (ROOT / 'frontend/guidance.js').read_text())

    def test_tutorial_distinguishes_evidence_model_and_publication(self):
        text = GUIDE.read_text()
        for boundary in ('不代表品牌客户', '不会被写成 AI 审核通过',
                         '视频没有自动配音', '不要把搜索摘要当作已读正文',
                         '平台实际发布之后', '不能算视频已做好',
                         '不能直接访问', '达到次数上限'):
            self.assertIn(boundary, text)


if __name__ == '__main__':
    unittest.main()

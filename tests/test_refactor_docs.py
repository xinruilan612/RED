"""Documentation handoff checks; no database, network or product execution."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RefactorDocumentationTests(unittest.TestCase):
    def test_single_existing_requirement_and_progress_entry(self):
        req = ROOT / 'docs/design/CONNECTED_CREATOR_REQUIREMENTS.md'
        progress = ROOT / 'docs/CONNECTED_CREATOR_STATUS.md'
        self.assertTrue(req.is_file())
        self.assertTrue(progress.is_file())
        for entry in ('AGENTS.md', 'README.md'):
            text = (ROOT / entry).read_text()
            self.assertIn(str(req.relative_to(ROOT)), text)
            self.assertIn(str(progress.relative_to(ROOT)), text)
        self.assertFalse((ROOT / 'docs/REFACTOR_REQUIREMENTS.md').exists())
        self.assertFalse((ROOT / 'docs/REFACTOR_PLAN.md').exists())

    def test_requirement_coverage_and_staged_handoff(self):
        text = (ROOT / 'docs/design/CONNECTED_CREATOR_REQUIREMENTS.md').read_text()
        ids = re.findall(r'^\| (R\d+) \|', text, re.M)
        self.assertEqual(ids, [f'R{i:02d}' for i in range(1, 14)])
        progress = (ROOT / 'docs/CONNECTED_CREATOR_STATUS.md').read_text()
        stages = re.findall(r'^\| ([1-6] [^|]+) \|', progress, re.M)
        self.assertEqual([s.strip() for s in stages], [
            '1 说明对齐', '2 工作台与 RAG', '3 模型与资料输入',
            '4 四 Agent 协作', '5 评论复盘与发布', '6 完整验收'])
        for label in ('已验证', '有代码但未验证', '缺失', '未知'):
            self.assertIn(label, progress)

    def test_runtime_changes_remain_pending_in_every_role(self):
        for card in sorted((ROOT / 'docs/agents').glob('0[1-4]*.md')):
            text = card.read_text()
            with self.subTest(card=card.name):
                self.assertIn('本轮改版目标职责（待运行时联动）', text)
                self.assertIn('新增职责尚待阶段四', text)
                self.assertIn('backend/live.py::messages_for', text)
                self.assertIn('本卡片不被直接加载为运行提示词', text)

    def test_sensitive_boundaries_are_explicit(self):
        text = (ROOT / 'docs/design/CONNECTED_CREATOR_REQUIREMENTS.md').read_text()
        for rule in ('不填 0、不编造', '保留后台评论归纳能力、数据表与历史数据',
                     '不回传明文', 'SKP / SKAPP', '准确链接尚未确定',
                     '开发功能不等于授权替用户公开发帖',
                     '不修改业务代码、运行时 Prompt、数据库、依赖'):
            self.assertIn(rule, text)
        self.assertNotRegex(text, r'https?://\S*(?:skapp|skp)')


if __name__ == '__main__':
    unittest.main()

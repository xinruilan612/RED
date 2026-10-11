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
                if card.name.startswith('03_'):
                    self.assertIn('本轮原创文案运行时职责', text)
                    self.assertIn('已联动实际 Prompt', text)
                else:
                    self.assertIn('本轮改版目标职责（待运行时联动）', text)
                    self.assertIn('新增职责尚待阶段四', text)
                self.assertIn('backend/live.py::messages_for', text)
                self.assertIn('本卡片不被直接加载为运行提示词', text)

    def test_phase_two_scope_clarifications(self):
        text = (ROOT / 'docs/design/CONNECTED_CREATOR_REQUIREMENTS.md').read_text()
        for rule in ('仅第一阶段适用', '用户主动上传并授权的私有产品资料', '第二阶段允许完成检索', '全面提示词重写及完整对话改稿留到第四阶段'):
            self.assertIn(rule, text)

    def test_background_search_and_confirmation_scope(self):
        text=(ROOT/'docs/design/CONNECTED_CREATOR_REQUIREMENTS.md').read_text()
        for phrase in ('第二轮具体修正', '无界面', '稳定笔记ID', '候选', '加入知识库', '不绕过登录、验证码或访问限制'):
            self.assertIn(phrase,text)
        status=(ROOT/'docs/CONNECTED_CREATOR_STATUS.md').read_text()
        for phrase in ('站内搜索交互修复与数据库核验', 'current_database/current_schema', '不是本次 8775 业务数据源', '不保证全站最高', '部分失败与恢复为替身回归', '跨主题通用修复', '未发出；保留输入', '同一搜索版本的三主题真实验收'):
            self.assertIn(phrase,status)

    def test_sensitive_boundaries_are_explicit(self):
        text = (ROOT / 'docs/design/CONNECTED_CREATOR_REQUIREMENTS.md').read_text()
        for rule in ('不填 0、不编造', '保留后台评论归纳能力、数据表与历史数据',
                     '不回传明文', 'SKP / SKAPP', '准确链接尚未确定',
                     '开发功能不等于授权替用户公开发帖',
                     '仅第一阶段适用'):
            self.assertIn(rule, text)
        self.assertNotRegex(text, r'https?://\S*(?:skapp|skp)')


if __name__ == '__main__':
    unittest.main()

"""Requirements guards: prevent authorization and completion claims drifting."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "CONNECTED_CREATOR_REQUIREMENTS.md"

class ConnectedCreatorRequirementsTests(unittest.TestCase):
    def test_current_entrypoints_reference_single_baseline(self):
        paths = [ROOT/"AGENTS.md", ROOT/"README.md", ROOT/"docs/DEPLOYMENT.md",
                 ROOT/"docs/IMPLEMENTATION_STATUS.md", *sorted((ROOT/"docs/design").glob("*.md")),
                 *sorted((ROOT/"docs/agents").glob("*.md"))]
        for path in paths:
            if path.name == BASELINE:
                continue
            with self.subTest(path=path.name):
                self.assertIn(BASELINE, path.read_text())

    def test_planned_extension_does_not_grant_publication_or_paid_testing(self):
        c = json.loads((ROOT/"docs/design/design_contract.json").read_text())
        x = c["connected_creator_extension"]
        self.assertEqual(x["status"], "planned")
        self.assertEqual(c["agents"], ["audience", "research", "content", "reviewer"])
        self.assertFalse(x["publishing_authorized"])
        self.assertTrue(x["paid_testing_requires_explicit_budget"])
        self.assertTrue(x["readonly_real_account_validation_authorized"])
        self.assertIn("missing_is_null", x["truth_boundaries"])
        self.assertIn("owner", x["sync_required_fields"])
        self.assertIn("account_id", x["sync_required_fields"])

    def test_platform_permission_gate_and_runtime_truth_are_explicit(self):
        text = (ROOT/"docs/design"/BASELINE).read_text()
        for requirement in ("自动同步仅在获得适用平台授权渠道后启用", "不实施绕限制采集",
                            "轮询标注自动同步与实际间隔", "BYOK 失败不静默回退",
                            "backend/live.py", "backend/operations_planner.py", "backend/windtunnel.py",
                            "文档不会自动改变运行时", "搜索摘要", "混合 RAG"):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, text)


class ConnectedCreatorDeliveryDocumentationTests(unittest.TestCase):
    def test_delivery_distinguishes_isolated_acceptance_and_external_gates(self):
        text=(ROOT/'docs/CONNECTED_CREATOR_STATUS.md').read_text()
        for phrase in ('8775', 'SCHEMA_TOO_NEW', '另一 worktree', '18570', 'partial',
                       '1 份知乎正文', '未知互动指标不能称为爆款', '未提取 Cookie',
                       '未进行公网部署', '未进行收费模型真实调用'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase,text)
        for path in ('README.md','AGENTS.md','docs/DEPLOYMENT.md','docs/IMPLEMENTATION_STATUS.md',
                     'docs/design/CONNECTED_CREATOR_REQUIREMENTS.md','docs/LOCAL_RAG.md'):
            with self.subTest(path=path):
                self.assertIn('CONNECTED_CREATOR_STATUS.md',(ROOT/path).read_text())

    def test_official_login_is_not_platform_data_authorization(self):
        text=(ROOT/'docs/research/XHS_CONNECTION_FEASIBILITY.md').read_text()
        self.assertNotIn('未登录账号',text)
        for phrase in ('用户已亲自', '按小时更新', '上传 Skill', '不等于',
                       'automatic_sync_available=false', '未提取 Cookie'):
            self.assertIn(phrase,text)

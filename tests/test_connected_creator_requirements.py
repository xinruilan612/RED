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
        for requirement in ("用户明确授权非商业本人账号读取及有限公开案例研究", "不实施绕限制采集",
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
                       '未进行公网部署', '$0.0184536', '15378 tokens', 'WAITING_USER'):
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


class ConnectedCreatorLatestAcceptanceTests(unittest.TestCase):
    def test_current_state_does_not_confuse_qr_video_description_and_completed_capture(self):
        text=(ROOT/'docs/CONNECTED_CREATOR_STATUS.md').read_text()
        for phrase in ('扫码重连后', '不是视频音轨转写', '视频文字描述',
                       '本人笔记', '评论不随', '冻结版本', '15分钟定时读取',
                       '非空评论和逐笔流量仍未实测', '待校对原始版本不参与检索',
                       '8次真实调用', '$0.05', '不构成官方API许可'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase,text)

    def test_sync_worker_and_rag_docs_describe_current_entrypoints(self):
        sync=(ROOT/'docs/XHS_LOCAL_SYNC.md').read_text()
        self.assertIn('统一工作进程',sync)
        self.assertNotIn('网页内尚无自助扫码重连流程',sync)
        self.assertNotIn('仅允许 login/status、user/me、feeds/detail 三个',sync)
        self.assertIn('每页50条',sync)
        rag=(ROOT/'docs/LOCAL_RAG.md').read_text()
        self.assertIn('export_versions',rag)
        self.assertIn('document_id/expected_version',rag)
        self.assertIn('评论不进入',rag)


class CreatorDOMDocumentationTests(unittest.TestCase):
    def test_creator_reader_and_full_integration_have_separate_evidence(self):
        sync = (ROOT/'docs/XHS_LOCAL_SYNC.md').read_text()
        status = (ROOT/'docs/CONNECTED_CREATOR_STATUS.md').read_text()
        for phrase in ('scripts/xhs_creator_reader.py', 'creator_account_id', 'source_id',
                       '--login', 'bootstrap', '独立profile', '单篇曝光', 'source_updated_at=null'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, sync)
        for phrase in ('08:06:33.190213Z', '24/17/7/8/30', '8.7%', 'Worker持久化',
                       '联调已验收', '原MCP笔记及评论采集独立', '不提交Git',
                       'creator-integration.json', '16:12:07', '16:27:07', '900秒',
                       '首屏最多30张', '平台源更新时间未知', '不点击切换周期'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, status)

    def test_completed_case_research_is_not_still_described_as_queued(self):
        for path in ('README.md', 'docs/XHS_LOCAL_SYNC.md', 'docs/CONNECTED_CREATOR_STATUS.md',
                     'docs/DEPLOYMENT.md', 'docs/design/CONNECTED_CREATOR_REQUIREMENTS.md'):
            text = (ROOT/path).read_text()
            with self.subTest(path=path):
                self.assertNotIn('研究已排队', text)
                self.assertNotIn('研究排队待结果', text)
                self.assertNotIn('页面联调待验收', text)
                self.assertNotIn('页面联调尚待验收', text)
                self.assertNotIn('不读取创作者后台流量', text)
                self.assertIn('3份', text)

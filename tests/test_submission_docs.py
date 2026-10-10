"""Check competition statements against current contracts and recorded evidence."""
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs/submission'


class SubmissionDocumentsTests(unittest.TestCase):
    def test_evidence_matches_actual_case_log(self):
        record = json.loads((DOCS / 'evidence/verification.json').read_text())
        log = (DOCS / 'evidence/baseline-tests.log').read_text()
        baseline = record['baseline']
        self.assertEqual(len(re.findall(r'\) \.\.\. ok$', log, re.M)), baseline['run'])
        self.assertEqual(sum(baseline['modules'].values()), baseline['run'])
        self.assertIn(f"Ran {baseline['run']} tests in {baseline['elapsed_seconds']:.3f}s", log)
        self.assertTrue(log.rstrip().endswith('OK'))
        self.assertEqual((baseline['failures'], baseline['errors'], baseline['skipped']), (0, 0, 0))

    def test_source_fingerprints_match_product_baseline(self):
        manifest = json.loads((DOCS / 'evidence/source-manifest.json').read_text())
        for relative, expected in manifest.items():
            with self.subTest(source=relative):
                # These are 2026-09-21 evidence, not assertions that newer features
                # must keep the old product source unchanged. Snapshots were read
                # from verification.json's product_commit and retain its hashes.
                archived = DOCS / 'evidence/baseline-source' / (relative + '.snapshot')
                self.assertEqual(hashlib.sha256(archived.read_bytes()).hexdigest(), expected)

    def test_required_sections_and_implementation_limits(self):
        proposal = (DOCS / '01_技术方案.md').read_text()
        for section in ('一 产品概述与定位', '二 技术架构与创新', '三 功能设计与实现',
                        '四 开发测试与部署', '五 应用价值与展望', '六 附录与依据'):
            self.assertIn(section, proposal)
        contract = json.loads((ROOT / 'docs/design/design_contract.json').read_text())
        algorithm = (DOCS / '03_核心算法说明.md').read_text()
        self.assertIn(f"租约为{contract['runtime_extension']['lease_s']}秒", algorithm)
        self.assertIn('本项目未训练或微调模型', algorithm)
        self.assertIn('未知', algorithm)
        report = (DOCS / '04_测试报告.md').read_text()
        self.assertIn('human_accepted=false', report)
        self.assertIn('没有重新录制', report)

    def test_current_positioning_and_case_do_not_claim_commercial_outcomes(self):
        proposal = (DOCS / '01_技术方案.md').read_text()
        self.assertIn('小品牌博主', proposal)
        self.assertIn('441359e', proposal)
        for score in ('创新性20分', '技术实现20分', '功能完整性20分', '方案完整性20分', '应用价值15分'):
            self.assertIn(score, proposal)
        script = (DOCS / '05_功能演示录制脚本.md').read_text()
        for boundary in ('M185', '不是商业客户', '待试读', '普通AI', '5位', '不会', '当前视频未录制'):
            self.assertIn(boundary, script)
        self.assertNotIn('通过169项工程测试', script)
        report = (DOCS / '04_测试报告.md').read_text()
        self.assertIn('540项', report)
        self.assertIn('101项', report)
        self.assertIn('尚待实际执行', report)
        self.assertIn('9月21日', report)
        manual = (DOCS / '02_软件说明书.md').read_text()
        self.assertNotIn('当前不提供视频生成或图片包自动导出', manual)
        self.assertIn('无声图文MP4', manual)

    def test_official_outline_has_six_unique_chapters_and_subsections(self):
        proposal = (DOCS / '01_技术方案.md').read_text()
        chapters = re.findall(r'^## (.+)$', proposal, re.M)
        self.assertEqual(chapters, ['一 产品概述与定位', '二 技术架构与创新', '三 功能设计与实现',
                                    '四 开发测试与部署', '五 应用价值与展望', '六 附录与依据'])
        for section in ('1.1 背景与目标', '1.2 产品定位', '2.1 整体架构', '2.2 技术选型',
                        '2.3 创新应用', '3.1 核心功能', '3.2 辅助功能', '3.3 扩展性设计',
                        '4.1 开发流程', '4.2 代码实现', '4.3 测试方案', '4.4 本地安装',
                        '5.1 实际应用场景', '5.2 市场分析', '5.3 成果总结', '5.4 未来规划',
                        '6.1 软件设计资料', '6.2 核心代码', '6.3 测试数据', '6.4 参考文献', '6.5 其他佐证'):
            self.assertIn('### ' + section, proposal)
        self.assertEqual(proposal.count('[[architecture]]'), 1)
        self.assertEqual(proposal.count('[[workflow]]'), 1)
        self.assertIn('260506-1.pdf', proposal)

    def test_current_proposal_separates_package_quality_and_pending_acceptance(self):
        proposal = (DOCS / '01_技术方案.md').read_text()
        for fact in ('27a184d', 'paid_model_calls=0', '各导出2张1080×1440 PNG',
                     '正文与PDF专项11项验证完成', 'CI及实际包结果待验收', 'SKAPP/ChineseCLIP',
                     '生产库写入为false', '本文同步提供可编辑正文与对应技术方案PDF', '不证明真实模型质量'):
            self.assertIn(fact, proposal)
        self.assertIn('SKAPP/ChineseCLIP实验模块不随本次包安装', proposal)
        self.assertIn('DeepSeek创作、读者检查、改稿复审、单张与全文导出', proposal)
        self.assertIn('现有Mac实验环境不受影响', proposal)
        self.assertIn('没有可信市场规模', proposal)
        self.assertIn('团队实名及具体分工待团队确认', proposal)
        self.assertIn('未训练新基础模型', proposal)

    def test_current_feedback_is_not_erased_or_reassigned_to_new_package(self):
        proposal = (DOCS / '01_技术方案.md').read_text()
        for fact in ('三位真实读者', '无需重复收集', '4.00 | 2.67', '4.33 | 3.00',
                     '排除P03后前两人可信均为4', '绑定旧稿', 'Codex代理不是这三位真人',
                     '描述10月4日历史案例'):
            self.assertIn(fact, proposal)

    def test_real_case_preserves_manual_adoption_and_comparison_limits(self):
        record = json.loads((DOCS / 'evidence/current-case.json').read_text())
        self.assertEqual(record['acceptance_mode'], 'manual_override')
        self.assertFalse(record['final_ai_review_passed'])
        self.assertEqual((record['system_calls'], record['system_tokens']), (13, 24714))
        self.assertEqual((record['ordinary_ai_calls'], record['ordinary_ai_tokens']), (1, 811))
        self.assertEqual((record['reader_forms_prepared'], record['reader_responses_received']), (5, 0))
        self.assertFalse(record['comparison_boundary']['strict_controlled_comparison'])
        self.assertFalse(record['comparison_boundary']['ordinary_allow_hypothesis'])
        self.assertTrue(record['comparison_boundary']['system_allow_hypothesis_final'])
        report = (DOCS / '04_测试报告.md').read_text()
        for limitation in ('未通过有效最终AI复审', '不能称完全同输入', '风格与措辞', '反馈0/5', '连续录屏'):
            self.assertIn(limitation, report)
        log = (DOCS / 'evidence/current-tests.log').read_bytes()
        self.assertEqual(hashlib.sha256(log).hexdigest(), record['tests']['log_sha256'])

    def test_identity_privacy_and_source_paths(self):
        paths = sorted(DOCS.glob('[0-9][0-9]_*.md'))
        self.assertEqual(len(paths), 6)
        for path in paths:
            text = path.read_text()
            self.assertIn('47191919', text)
            self.assertNotIn('/Users/', text)
            self.assertNotRegex(text, r'(?:sk-[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9]{20,})')
            for relative in re.findall(r'\b(?:backend|frontend|docs|tests)/[A-Za-z0-9_./-]+\.(?:py|md|json|js)', text):
                self.assertTrue((ROOT / relative).is_file(), relative)

    def test_submission_limits_and_unfinished_items_are_explicit(self):
        guide = (DOCS / '00_提交清单与待填项.md').read_text()
        brief = guide.split('作品简介：', 1)[1].split('\n', 1)[0]
        self.assertLessEqual(len(brief), 300)
        for boundary in ('没有单列作品上传截止日', '未取得模板原文件',
                         '脚本不能替代视频', '本包未制作答辩幻灯片', '目前未填写公网地址'):
            self.assertIn(boundary, guide)
        self.assertIn('notice/notice-2/4815.html', guide)


if __name__ == '__main__':
    unittest.main()

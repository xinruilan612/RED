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

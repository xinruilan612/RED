"""Guard document links and prevent mixing unverified screenshot rules into AIC rules."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ContestDocumentationTests(unittest.TestCase):
    def setUp(self):
        self.document = (ROOT / 'docs/CONTEST_REQUIREMENTS.md').read_text(encoding='utf-8')

    def test_authoritative_sources_present(self):
        for url in (
            'https://www.aicomp.cn/notice/notice-1/3674.html',
            'https://www.aicomp.cn/tracks/tracks-2/3792.html',
        ):
            self.assertIn(url, self.document)

    def test_screenshot_requirements_are_separate(self):
        official, rest = self.document.split('## 3. 截图要求', 1)
        screenshot, recommendations = rest.split('## 4.', 1)
        self.assertNotIn('8000', official)
        self.assertNotIn('5 分钟', official)
        self.assertIn('待确认适用性', screenshot)
        self.assertIn('不能用截图', screenshot)
        self.assertIn('非官方新增要求', recommendations)

    def test_score_weights_total_100(self):
        table = self.document.split('| 评分维度 | 分值 |', 1)[1].split('官方参考大纲', 1)[0]
        rows = re.findall(r'\| ([^|]+?) \| (\d+) \|', table)
        scores = {label: int(value) for label, value in rows}
        total = scores.pop('合计')
        self.assertEqual(len(scores), 6)
        self.assertEqual(total, 100)
        self.assertEqual(sum(scores.values()), total)

    def test_repository_markdown_links_resolve(self):
        for path in (ROOT / 'AGENTS.md', ROOT / 'docs/CONTEST_REQUIREMENTS.md'):
            for target in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
                if '://' in target or target.startswith('#'):
                    continue
                with self.subTest(path=path.name, target=target):
                    self.assertTrue((path.parent / target.split('#')[0]).is_file())

    def test_agent_entry_points_to_requirements(self):
        self.assertIn('docs/CONTEST_REQUIREMENTS.md', (ROOT / 'AGENTS.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()

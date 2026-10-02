"""The current acceptance explanation must be discoverable and honest."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'docs/validation/REAL_ACCOUNT_ACCEPTANCE_20261002.md'


class RealAccountDeliveryDocs(unittest.TestCase):
    def test_report_is_linked_and_local_references_resolve(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn('docs/validation/REAL_ACCOUNT_ACCEPTANCE_20261002.md', readme)
        text = REPORT.read_text(encoding='utf-8')
        for target in re.findall(r'\]\(([^)]+)\)', text):
            if target.startswith(('https://', 'http://', '#')):
                continue
            with self.subTest(target=target):
                self.assertTrue((REPORT.parent / target.split('#')[0]).is_file())

    def test_real_website_account_is_not_presented_as_social_authorization(self):
        text = REPORT.read_text(encoding='utf-8')
        for boundary in ('未接社媒授权', 'manual_override', '不是供应商账单', '未验证'):
            self.assertIn(boundary, text)
        self.assertNotIn('所有环境完美兼容', text)


if __name__ == '__main__':
    unittest.main()

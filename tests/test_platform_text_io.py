"""Keep scoped material-tool text I/O independent of the system locale."""
import ast
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class PlatformTextIOTests(unittest.TestCase):
    def test_material_tools_explicitly_use_utf8_for_path_text_io(self):
        for filename in ('build_design_atlas.py', 'build_submission_docs.py',
                         'package_submission.py', 'package_windtunnel.py'):
            source = ROOT / 'scripts' / filename
            tree = ast.parse(source.read_text(encoding='utf-8'), filename=str(source))
            calls = [node for node in ast.walk(tree)
                     if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                     and node.func.attr in {'read_text', 'write_text'}]
            self.assertTrue(calls, f'{filename} must retain its tested text I/O calls')
            for call in calls:
                with self.subTest(script=filename, line=call.lineno, method=call.func.attr):
                    encoding = next((keyword.value for keyword in call.keywords
                                     if keyword.arg == 'encoding'), None)
                    self.assertIsInstance(encoding, ast.Constant)
                    self.assertEqual(encoding.value, 'utf-8')

    def fixture(self, root):
        root = root.resolve()
        (root / 'scripts').mkdir()
        (root / 'docs' / 'agents').mkdir(parents=True)
        (root / 'docs' / 'design').mkdir()
        shutil.copyfile(ROOT / 'scripts' / 'sync_agent_cards.py', root / 'scripts' / 'sync_agent_cards.py')
        overview = root / 'docs' / 'agents' / '00_overview_and_all_agents.md'
        overview.write_text('# 四角色规范 📚\n\n**以下为四份独立 Agent Card 的完整合并内容。**\n旧合并内容\n', encoding='utf-8')
        for number, role in enumerate(('audience', 'research', 'content', 'reviewer'), 1):
            card = (f'# 中文角色 {role} 📚\n\nAgent ID：`{role}`\n'
                    '## 5. 允许的 Tools\n| `资料检索` | 读取来源 | 当前账号 |\n'
                    '## 6. 允许的 Skills\n- `事实核查`：保留原文出处\n'
                    '## 7. 其他约束\n不得伪造真实反馈。\n')
            (overview.parent / f'0{number}_{role}.md').write_text(card, encoding='utf-8')
        return root / 'scripts' / 'sync_agent_cards.py', overview

    def legacy_text_locale(self):
        original_read, original_write = Path.read_text, Path.write_text

        def read(path, *args, **kwargs):
            kwargs.setdefault('encoding', 'gbk')
            return original_read(path, *args, **kwargs)

        def write(path, content, *args, **kwargs):
            kwargs.setdefault('encoding', 'gbk')
            return original_write(path, content, *args, **kwargs)

        return patch.object(Path, 'read_text', read), patch.object(Path, 'write_text', write)

    def test_preview_reads_utf8_cards_under_gbk_defaults_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            # macOS aliases /var to /private/var; match the script's __file__.resolve().
            root = Path(directory).resolve()
            script, overview = self.fixture(root)
            before = overview.read_bytes()
            read_patch, write_patch = self.legacy_text_locale()
            with read_patch, write_patch:
                namespace = runpy.run_path(str(script))
                output = namespace['outputs']()
            self.assertIn('中文角色 audience 📚', output[overview])
            self.assertIn('读取来源', output[root / 'docs' / 'design' / 'AGENT_REGISTRY.md'])
            self.assertEqual(overview.read_bytes(), before)
            self.assertFalse((root / 'docs' / 'design' / 'AGENT_REGISTRY.md').exists())

    def test_main_writes_utf8_to_copied_cards_under_gbk_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            script, overview = self.fixture(root)
            read_patch, write_patch = self.legacy_text_locale()
            with read_patch, write_patch:
                runpy.run_path(str(script), run_name='__main__')
            merged = overview.read_text(encoding='utf-8')
            registry = (root / 'docs' / 'design' / 'AGENT_REGISTRY.md').read_text(encoding='utf-8')
            self.assertIn('# 四角色规范 📚', merged)
            self.assertIn('中文角色 reviewer 📚', merged)
            self.assertNotIn('旧合并内容', merged)
            self.assertIn('| audience | `资料检索` | 读取来源 | 当前账号 |', registry)
            self.assertIn('| reviewer | `事实核查` | 保留原文出处 |', registry)


if __name__ == '__main__':
    unittest.main()

"""Confirmed-draft DOCX exports preserve the existing ownership and review guards."""
import copy
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.provider import Config
from backend.store import Store


def document_text(content):
    """Validate the actual OOXML payload and read text in document order."""
    with zipfile.ZipFile(io.BytesIO(content)) as package:
        assert package.testzip() is None
        for part in ('[Content_Types].xml', '_rels/.rels', 'word/document.xml'):
            assert part in package.namelist(), part
            ET.fromstring(package.read(part))
        document = ET.fromstring(package.read('word/document.xml'))
        return '\n'.join(node.text or '' for node in document.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))


class DocxRenderTests(unittest.TestCase):
    def test_render_produces_valid_ooxml_and_preserves_chinese_special_characters(self):
        from backend.draft_docx import render
        markdown = '# 中文确认稿 📝\n\n正文包含 A&B、<示例> 和 "引号"。\n\n- 第一项\n- 第二项\n\n#标签'
        content = render(markdown)
        self.assertIsInstance(content, bytes)
        self.assertTrue(content.startswith(b'PK'))
        text = document_text(content)
        for expected in ('中文确认稿 📝', 'A&B', '<示例>', '"引号"', '第一项', '第二项', '#标签'):
            self.assertIn(expected, text)

    def test_render_sanitizes_xml_invalid_controls_without_losing_visible_text(self):
        from backend.draft_docx import render
        text = document_text(render('# 测试\n\n前\x00中\x0b后\n下一行\t制表'))
        for expected in ('测试', '前中后', '下一行', '制表'):
            self.assertIn(expected, text)


class DocxExportApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'test.sqlite')
        self.app = create_app(self.store, Config(), origin='http://testserver', invite='')
        self.client = TestClient(self.app)
        self.csrf = self.client.get('/api/session').json()['csrf']
        self.register('docx_creator')

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def post(self, path, data):
        return self.client.post(path, json=data, headers={'Origin': 'http://testserver', 'X-CSRF-Token': self.csrf})

    def register(self, username):
        response = self.post('/api/auth/register', dict(username=username, password='Test-long-password'))
        self.assertEqual(response.status_code, 200, response.text)
        self.csrf = response.json()['csrf']

    def create_run(self, scenario='standard'):
        response = self.post('/api/runs', dict(topic='整理衣橱', audience='大学生', tone='真实清楚', material='一件白衬衫可搭配已有衣物', scenario=scenario, allow_hypothesis=True))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def act(self, run, action, payload=None):
        response = self.post('/api/runs/' + run['run_id'] + '/actions', dict(action=action, version=run['status_version'], key=str(uuid4()), payload=payload or {}))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def reviewed_run(self, scenario='standard'):
        run = self.create_run(scenario)
        for _ in range(10):
            if run.get('review'):
                break
            run = self.act(run, 'next')
        self.assertTrue(run.get('review'))
        self.assertEqual(run['usage']['model_calls'], 0)
        return run

    def confirm(self, run):
        return self.act(run, 'accept', dict(draft_ref=run['drafts'][-1]['ref'], review_ref=run['review']['ref']))

    def test_confirmed_draft_download_has_docx_mime_filename_and_exact_content(self):
        run = self.confirm(self.reviewed_run())
        response = self.client.get('/api/runs/' + run['run_id'] + '/export?format=docx')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['content-type'], 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        self.assertIn('attachment;', response.headers['content-disposition'])
        self.assertIn('.docx', response.headers['content-disposition'])
        text = document_text(response.content)
        draft = run['drafts'][-1]['content']
        self.assertNotIn('模拟创作稿（未调用真实 AI）', text)
        self.assertNotIn('AI 创作稿', text)
        self.assertIn(draft['selected_title'], text)
        for line in draft['body'].splitlines():
            if line.strip():
                self.assertIn(line.strip(), text)
        self.assertIn(draft['cta'], text)
        for tag in draft['tags']:
            self.assertIn('#' + tag, text)
        self.assertEqual(self.client.get('/api/runs/' + run['run_id']).json()['usage']['model_calls'], 0)

    def test_existing_default_markdown_export_remains_available(self):
        run = self.confirm(self.reviewed_run())
        response = self.client.get('/api/runs/' + run['run_id'] + '/export')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.headers['content-type'].startswith('text/markdown'))
        self.assertIn('.md', response.headers['content-disposition'])
        self.assertIn(run['drafts'][-1]['content']['selected_title'], response.text)

    def test_unconfirmed_draft_cannot_be_exported_as_docx(self):
        run = self.reviewed_run()
        response = self.client.get('/api/runs/' + run['run_id'] + '/export?format=docx')
        self.assertNotEqual(response.status_code, 200)
        self.assertEqual(response.json()['error']['code'], 'INVALID_TRANSITION')

    def test_other_owner_cannot_download_confirmed_docx(self):
        run = self.confirm(self.reviewed_run())
        self.assertEqual(self.post('/api/auth/logout', {}).status_code, 200)
        self.csrf = self.client.get('/api/session').json()['csrf']
        self.register('docx_other')
        response = self.client.get('/api/runs/' + run['run_id'] + '/export?format=docx')
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.content.startswith(b'PK'))

    def test_manual_adoption_export_is_clean_but_run_keeps_unapproved_review(self):
        run = self.reviewed_run('revision')
        self.assertEqual(run['review']['decision'], 'revision_required')
        review = copy.deepcopy(run['review'])
        draft = run['drafts'][-1]
        run = self.act(run, 'adopt_manual', dict(draft_ref=draft['ref'], content_hash=draft['content_hash'], acknowledge=True))
        response = self.client.get('/api/runs/' + run['run_id'] + '/export?format=docx')
        self.assertEqual(response.status_code, 200, response.text)
        text = document_text(response.content)
        self.assertNotIn('用户人工采用', text)
        self.assertNotIn('未通过 AI 审核', text)
        self.assertNotIn('审核意见保留', text)
        self.assertIn(draft['content']['selected_title'], text)
        after = self.client.get('/api/runs/' + run['run_id']).json()
        self.assertEqual(after['review'], review)
        self.assertEqual(after['acceptance']['mode'], 'manual_override')
        self.assertEqual(after['usage']['model_calls'], 0)

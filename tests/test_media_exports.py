import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
import zipfile
from unittest.mock import patch

from backend.contracts import DomainError
from backend.media_exports import capabilities, confirmed_snapshot, export_run, font_path, wrap_text
from backend.workflow import Run, digest


def fixture(body='第一步：洗脸后先保湿。\n第二步：出门前做好防晒。'):
    run = Run('owner', 'snapshot', context={'mode': 'live'})
    c = {'selected_title': '新手早间护肤：先保湿再防晒', 'body': body, 'cta': '你有什么护肤问题？', 'tags': ['护肤']}
    run.drafts = [{'ref': 'draft@1', 'content': c, 'content_hash': digest(c), 'snapshot_id': 'snapshot'}]
    run.accepted_ref = 'draft@1'
    run.acceptance = {'draft_ref': 'draft@1', 'content_hash': digest(c), 'snapshot_id': 'snapshot', 'mode': 'reviewed'}
    run.run_status = 'SUCCEEDED'
    return run


class MediaExportsTests(unittest.TestCase):
    def test_requires_confirmed_version_and_rejects_hash_change(self):
        run = fixture()
        run.run_status = 'RUNNING'
        with self.assertRaises(DomainError): export_run(run)
        run.run_status = 'SUCCEEDED'
        run.drafts[0]['content']['body'] = 'changed'
        with self.assertRaises(DomainError): confirmed_snapshot(run)

    def test_uses_accepted_ref_not_unconfirmed_latest(self):
        run = fixture()
        run.drafts.append({'ref': 'other', 'content': {'body': 'wrong'}})
        self.assertEqual(confirmed_snapshot(run)['draft_ref'], 'draft@1')

    def test_storyboard_is_real_text_and_traceable(self):
        data, mime, name = export_run(fixture(), 'storyboard')
        with zipfile.ZipFile(BytesIO(data)) as archive:
            self.assertIn('00:00:00,000 -->', archive.read('subtitles.srt').decode())
            manifest = json.loads(archive.read('manifest.json'))
            for row in manifest['files']:
                self.assertEqual(row['sha256'], hashlib.sha256(archive.read(row['name'])).hexdigest())
        self.assertEqual(mime, 'application/zip')
        self.assertTrue(name.endswith('.zip'))

    def test_real_png_render_and_no_text_loss(self):
        from PIL import Image, ImageFont
        body = '完整中文段落，不应被截断。' * 100
        lines = wrap_text(body, ImageFont.truetype(font_path(), 42), 900)
        self.assertEqual(''.join(lines), body)
        self.assertTrue(all(ImageFont.truetype(font_path(), 42).getlength(line) <= 900 for line in lines))
        data, _, _ = export_run(fixture(body))
        with zipfile.ZipFile(BytesIO(data)) as archive:
            pages = [name for name in archive.namelist() if name.endswith('.png')]
            self.assertGreater(len(pages), 2)
            self.assertEqual(Image.open(BytesIO(archive.read(pages[0]))).size, (1080, 1440))
            self.assertIn(body, archive.read('caption.txt').decode())

    def test_real_mp4_readable_duration_and_frame(self):
        import imageio_ffmpeg
        data, _, _ = export_run(fixture(), 'video')
        with zipfile.ZipFile(BytesIO(data)) as archive, tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'video.mp4'
            path.write_bytes(archive.read('video.mp4'))
            reader = imageio_ffmpeg.read_frames(str(path), pix_fmt='rgb24')
            meta = next(reader)
            self.assertEqual(meta['size'], (720, 960))
            self.assertAlmostEqual(meta['duration'], 16, delta=0.1)
            self.assertEqual(len(next(reader)), 720 * 960 * 3)
            reader.close()
            manifest = json.loads(archive.read('manifest.json'))
            self.assertFalse(manifest['video']['audio'])

    def test_unavailable_video_fails_explicitly(self):
        with patch('backend.media_exports.capabilities', return_value={'video_available': False}):
            with self.assertRaises(DomainError): export_run(fixture(), 'video')

    def test_video_timeout_cleans_temporary_files(self):
        import backend.media_exports as media
        real_temporary = tempfile.TemporaryDirectory
        folders = []
        def temporary(*args, **kwargs):
            result = real_temporary(*args, **kwargs)
            folders.append(result.name)
            return result
        with patch.object(media, 'capabilities', return_value={'video_available': True, 'images_available': True}), patch.object(media.tempfile, 'TemporaryDirectory', side_effect=temporary), patch.object(media.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ffmpeg', 90)):
            with self.assertRaises(DomainError): export_run(fixture(), 'video')
        self.assertTrue(folders)
        self.assertTrue(all(not Path(folder).exists() for folder in folders))

    def test_complete_bundle_real_files_and_sanitized_execution(self):
        run = fixture()
        run.acceptance.update(mode='manual_override', owner='private-owner', api_key='SecretNeverExport', acknowledged_issues=[{'text': 'SecretNeverExport'}])
        run.context['evidence'] = [{'source_id': 'public-source', 'url': 'https://example.org/help?token=SecretNeverExport#private'}]
        execution = {'usage': {'model_calls': 13, 'tokens': 24714, 'unknown_calls': 0},
            'owner': 'private-owner', 'api_key': 'SecretNeverExport',
            'review_execution': {'used': 3, 'limit': 3, 'remaining': 0, 'exhausted': True},
            'calls': [{'id': 'call-1', 'agent': 'reviewer', 'stage': 'review', 'status': 'completed', 'tokens': 10,
                       'diagnostic_response': 'SecretNeverExport', 'prompt': 'SecretNeverExport', 'owner': 'private-owner'}]}
        data, _, name = export_run(run, 'complete', execution)
        self.assertIn('complete', name)
        with zipfile.ZipFile(BytesIO(data)) as archive:
            for filename in ('images/01.png', 'video/video.mp4', 'storyboard/subtitles.srt', 'storyboard/storyboard.md', 'caption.txt', '使用说明.txt', 'execution-evidence.json', 'manifest.json'):
                self.assertIn(filename, archive.namelist())
            self.assertIsNone(archive.testzip())
            manifest = json.loads(archive.read('manifest.json'))
            for row in manifest['files']:
                self.assertEqual(row['sha256'], hashlib.sha256(archive.read(row['name'])).hexdigest())
            evidence = json.loads(archive.read('execution-evidence.json'))
            self.assertEqual(evidence['usage']['model_calls'], 13)
            self.assertEqual(evidence['draft_ref'], run.accepted_ref)
            self.assertFalse(evidence['final_ai_review_passed'])
            self.assertEqual(evidence['review_calls']['remaining'], 0)
            self.assertEqual(evidence['sources'][0]['url'], 'https://example.org/help')
            for name in ('execution-evidence.json', 'manifest.json', '使用说明.txt'):
                self.assertNotIn('SecretNeverExport', archive.read(name).decode())
                self.assertNotIn('private-owner', archive.read(name).decode())
            self.assertIn('不与无声翻页视频逐页同步', archive.read('使用说明.txt').decode())

    def test_complete_bundle_reports_missing_video_without_faking_file(self):
        from backend.contracts import DomainError
        with patch('backend.media_exports._video', side_effect=DomainError('MEDIA_UNAVAILABLE', '视频编码器不可用')):
            data, _, _ = export_run(fixture(), 'complete')
        with zipfile.ZipFile(BytesIO(data)) as archive:
            self.assertNotIn('video/video.mp4', archive.namelist())
            self.assertIn('video/未生成说明.txt', archive.namelist())
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['media_status']['video']['status'], 'unavailable')
            self.assertIn('视频编码器不可用', archive.read('使用说明.txt').decode())

    def test_complete_bundle_does_not_claim_live_calls_without_ledger(self):
        data, _, _ = export_run(fixture(), 'complete')
        with zipfile.ZipFile(BytesIO(data)) as archive:
            evidence = json.loads(archive.read('execution-evidence.json'))
            self.assertIsNone(evidence['usage']['model_calls'])
            self.assertEqual(evidence['calls'], [])

    def test_source_instructions_use_saved_sources_deduplicate_and_preserve_caption(self):
        from backend.contracts import DomainError
        body = '本文据公开资料整理，非亲测、非品牌合作。'
        run = fixture(body)
        run.context['evidence'] = [
            {'source_id': 'kb:a', 'title': '另一品牌说明书', 'url': 'https://user:secret@example.org/product?token=secret#private'},
            {'source_id': 'kb:b', 'title': '重复片段', 'url': 'https://example.org/product?session=secret'},
            {'source_id': 'kb:c', 'document_id': 'doc-1', 'version': 2, 'title': '用户提供资料'},
            {'source_id': 'kb:d', 'document_id': 'doc-1', 'version': 2, 'title': '用户提供资料'},
        ]
        run.context['web_research'] = {'sources': [{'source_id': 'web-1', 'title': '另一来源', 'source_url': 'https://other.example.org/manual?key=secret'}]}
        with patch('backend.media_exports.render_images', side_effect=DomainError('MEDIA_UNAVAILABLE', '未配置字体')), patch('backend.media_exports._video', side_effect=DomainError('MEDIA_UNAVAILABLE', '未配置视频')):
            data, _, _ = export_run(run, 'complete')
        with zipfile.ZipFile(BytesIO(data)) as archive:
            instructions = archive.read('使用说明.txt').decode()
            self.assertIn('另一品牌说明书 — https://example.org/product', instructions)
            self.assertEqual(instructions.count('https://example.org/product'), 1)
            self.assertEqual(instructions.count('用户提供资料'), 1)
            self.assertIn('另一来源 — https://other.example.org/manual', instructions)
            self.assertNotIn('secret', instructions)
            self.assertNotIn('罗技', instructions)
            self.assertIn('由创作者按实际情况填写', instructions)
            c = run.drafts[0]['content']
            self.assertEqual(archive.read('caption.txt').decode(), c['selected_title'] + '\n\n' + body + '\n\n' + c['cta'] + '\n\n#护肤')
            self.assertEqual(run.drafts[0]['content']['body'], body)

    def test_missing_or_invalid_source_does_not_invent_provenance(self):
        from backend.media_exports import _safe_source, _source_instructions
        self.assertIn('未保存可列出的来源', _source_instructions([]))
        self.assertIn('未保存可列出的来源', _source_instructions([_safe_source({'url': 'file:///private/secret'})]))
        self.assertEqual(_safe_source({'url': 'https://[invalid'}), {})
        self.assertEqual(_safe_source({'url': 'https://user:password@example.org/path?api_key=private#private'})['url'], 'https://example.org/path')

    def test_material_sources_are_explicit_sanitized_and_unverified(self):
        from backend.media_exports import _source_instructions
        run = fixture()
        run.context['material'] = ('来源：https://user:secret@example.org/product?token=secret#private\n'
            'Source: https://example.org/product?token=second\n'
            '正文中的 https://irrelevant.example.org 不是来源声明。\n'
            '资料来源：[来源](https://other.example.org/manual)\n秘密原文不应导出到说明')
        snapshot = confirmed_snapshot(run)
        description = _source_instructions(snapshot['source_refs'], snapshot['user_material_provided'])
        self.assertEqual(description.count('https://example.org/product'), 1)
        self.assertIn('https://other.example.org/manual', description)
        self.assertIn('用户提供的来源链接（未独立核验）', description)
        for private in ('secret', 'second', 'private', '秘密原文', 'irrelevant.example.org'):
            self.assertNotIn(private, description)
        run.context['material'] = '用户提供的产品资料，无链接。'
        snapshot = confirmed_snapshot(run)
        self.assertIn('用户提供素材未记录', _source_instructions(snapshot['source_refs'], snapshot['user_material_provided']))

    def test_limits_unbounded_pages_and_invalid_kind(self):
        with self.assertRaises(DomainError): export_run(fixture('长' * 30000))
        with self.assertRaises(DomainError): export_run(fixture(), '../../unsafe')


if __name__ == '__main__': unittest.main()

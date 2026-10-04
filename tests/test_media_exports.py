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

    def test_limits_unbounded_pages_and_invalid_kind(self):
        with self.assertRaises(DomainError): export_run(fixture('长' * 30000))
        with self.assertRaises(DomainError): export_run(fixture(), '../../unsafe')


if __name__ == '__main__': unittest.main()

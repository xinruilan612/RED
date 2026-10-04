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

    def test_limits_unbounded_pages_and_invalid_kind(self):
        with self.assertRaises(DomainError): export_run(fixture('长' * 30000))
        with self.assertRaises(DomainError): export_run(fixture(), '../../unsafe')


if __name__ == '__main__': unittest.main()

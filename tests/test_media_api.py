"""Real PostgreSQL + authenticated HTTP verification of media downloads.

The draft is produced by the deterministic creation workflow, intentionally with
no paid model calls. Rendering and MP4 decoding use real libraries and binaries.
"""
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
import zipfile

from fastapi.testclient import TestClient
from backend.api import create_app
from backend.provider import Config
from backend.store import Store


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires actual PostgreSQL TEST_DATABASE_URL')
class MediaPostgresApiTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.base = os.environ['TEST_DATABASE_URL']
        self.schema = 'youji_media_test_' + uuid4().hex
        with psycopg.connect(self.base, autocommit=True) as db:
            db.execute('CREATE SCHEMA ' + self.schema)
        self.addCleanup(self.drop_schema)
        target = self.base + ('&' if '?' in self.base else '?') + 'options=-csearch_path%3D' + self.schema
        self.store = Store(target)
        self.app = create_app(self.store, Config(), origin='http://testserver', invite='')
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.csrf = self.client.get('/api/session').json()['csrf']

    def drop_schema(self):
        import psycopg
        with psycopg.connect(self.base, autocommit=True) as db:
            db.execute('DROP SCHEMA ' + self.schema + ' CASCADE')

    def post(self, path, body):
        return self.client.post(path, json=body, headers={'Origin': 'http://testserver', 'X-CSRF-Token': self.csrf})

    def register(self, name='media_creator'):
        response = self.post('/api/auth/register', {'username': name, 'password': 'Test-Media-2026'})
        self.assertEqual(response.status_code, 200, response.text)
        self.csrf = response.json()['csrf']
        return response.json()

    def create(self):
        response = self.post('/api/runs', {'topic': '整理衣橱', 'audience': '大学生', 'tone': '真实清楚',
            'material': '一件白衬衫可搭配已有衣物', 'scenario': 'standard', 'allow_hypothesis': True, 'mode': 'simulation'})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def action(self, run, name, payload=None):
        response = self.post('/api/runs/' + run['run_id'] + '/actions', {'action': name,
            'version': run['status_version'], 'key': uuid4().hex, 'payload': payload or {}})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def confirm(self, run):
        for _ in range(10):
            if run['run_status'] == 'WAITING_USER': break
            run = self.action(run, 'next')
        self.assertIn('accept', run['allowed_actions'])
        run = self.action(run, 'accept', {'draft_ref': run['drafts'][-1]['ref'], 'review_ref': run['review']['ref']})
        self.assertEqual(run['run_status'], 'SUCCEEDED')
        self.assertEqual(run['usage']['model_calls'], 0)
        return run

    def test_media_assets_have_browser_mime_and_nosniff(self):
        for name, mime in [('media_exports.js', 'text/javascript'), ('media_exports.css', 'text/css')]:
            with self.subTest(asset=name):
                response = self.client.get('/' + name)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers['content-type'].split(';')[0], mime)
                self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        index = self.client.get('/').text
        self.assertIn('media_exports.js', index)
        self.assertIn('media_exports.css', index)

    def test_login_required_and_cross_owner_isolation(self):
        for suffix in ['/media/capabilities', '/media-export?kind=images']:
            self.assertEqual(self.client.get('/api/runs/unknown' + suffix).status_code, 401)
        self.register()
        run = self.confirm(self.create())
        self.post('/api/auth/logout', {})
        self.csrf = self.client.get('/api/session').json()['csrf']
        self.register('other_media_creator')
        for suffix in ['/media/capabilities', '/media-export?kind=images', '/media-export?kind=video']:
            response = self.client.get('/api/runs/' + run['run_id'] + suffix)
            self.assertEqual(response.status_code, 404, response.text)
            self.assertNotIn(run['drafts'][-1]['content']['body'], response.text)

    def test_unconfirmed_draft_and_unknown_kind_rejected(self):
        self.register()
        run = self.create()
        for kind in ('images', 'video', 'storyboard'):
            response = self.client.get('/api/runs/' + run['run_id'] + '/media-export?kind=' + kind)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()['error']['code'], 'INVALID_TRANSITION')
        response = self.client.get('/api/runs/' + run['run_id'] + '/media-export?kind=unsafe')
        self.assertEqual(response.status_code, 400)

    def test_confirmed_exact_version_real_images_video_and_storyboard(self):
        from PIL import Image
        import imageio_ffmpeg
        self.register()
        run = self.confirm(self.create())
        base = '/api/runs/' + run['run_id']
        caps = self.client.get(base + '/media/capabilities')
        self.assertEqual(caps.status_code, 200, caps.text)
        self.assertTrue(caps.json()['images_available'])
        self.assertTrue(caps.json()['video_available'])
        for kind in ('images', 'video', 'storyboard'):
            with self.subTest(kind=kind):
                response = self.client.get(base + '/media-export?kind=' + kind)
                self.assertEqual(response.status_code, 200, response.text[:200])
                self.assertEqual(response.headers['content-type'], 'application/zip')
                self.assertIn('attachment;', response.headers['content-disposition'])
                with zipfile.ZipFile(BytesIO(response.content)) as archive:
                    manifest = json.loads(archive.read('manifest.json'))
                    self.assertEqual(manifest['draft_ref'], run['accepted_ref'])
                    self.assertEqual(manifest['content_hash'], run['acceptance']['content_hash'])
                    self.assertEqual(manifest['snapshot_id'], run['snapshot_id'])
                    self.assertEqual(manifest['mode'], 'simulation')
                    self.assertIn(run['drafts'][-1]['content']['body'], archive.read('caption.txt').decode())
                    for file in manifest['files']:
                        self.assertEqual(file['sha256'], hashlib.sha256(archive.read(file['name'])).hexdigest())
                    if kind == 'images':
                        self.assertEqual(Image.open(BytesIO(archive.read('01.png'))).size, (1080, 1440))
                    elif kind == 'video':
                        with tempfile.TemporaryDirectory() as folder:
                            path = Path(folder) / 'video.mp4'
                            path.write_bytes(archive.read('video.mp4'))
                            reader = imageio_ffmpeg.read_frames(str(path), pix_fmt='rgb24')
                            meta = next(reader)
                            self.assertEqual(meta['size'], (720, 960))
                            self.assertAlmostEqual(meta['duration'], manifest['video']['duration_seconds'], delta=.1)
                            self.assertEqual(len(next(reader)), 720 * 960 * 3)
                            reader.close()
                    else:
                        self.assertIn(' --> ', archive.read('subtitles.srt').decode())
        # Downloading is read-only: the accepted draft/version and paid ledger do not change.
        after = self.client.get(base).json()
        self.assertEqual(after['status_version'], run['status_version'])
        self.assertEqual(after['accepted_ref'], run['accepted_ref'])
        self.assertEqual(after['usage']['model_calls'], 0)


if __name__ == '__main__': unittest.main()

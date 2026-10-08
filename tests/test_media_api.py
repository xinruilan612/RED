"""Real PostgreSQL + authenticated HTTP verification of media downloads.

The draft is produced by the deterministic creation workflow, intentionally with
no paid model calls. Rendering and MP4 decoding use real libraries and binaries.
"""
from io import BytesIO
import hashlib
import base64
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

    def design_request(self,run):
        return {'template':'checklist','draft_ref':run['accepted_ref'],
                'content_hash':run['acceptance']['content_hash'],
                'options':{'page_styles':{'0':{'size':'large','accent':'orange'}}}}

    def test_preview_export_exact_png_design_binding_and_no_run_mutation(self):
        self.register();run=self.confirm(self.create());base='/api/runs/'+run['run_id']
        request=self.design_request(run)
        response=self.post(base+'/media-preview',request)
        self.assertEqual(response.status_code,200,response.text[:200])
        preview=response.json()
        self.assertEqual(preview['draft_ref'],run['accepted_ref'])
        self.assertEqual(preview['content_hash'],request['content_hash'])
        self.assertEqual(len(preview['design_hash']),64)
        response=self.post(base+'/media-export',dict(request,kind='images',design_hash=preview['design_hash']))
        self.assertEqual(response.status_code,200,response.text[:200] if response.status_code!=200 else '')
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['design_hash'],preview['design_hash'])
            for page in preview['pages']:
                self.assertEqual(archive.read(page['name']),base64.b64decode(page['data_url'].split(',',1)[1]))
        changed=dict(request,options={'page_styles':{'0':{'size':'normal','accent':'blue'}}},kind='images',design_hash=preview['design_hash'])
        self.assertEqual(self.post(base+'/media-export',changed).status_code,409)
        after=self.client.get(base).json()
        self.assertEqual(after['status_version'],run['status_version'])
        self.assertEqual(after['accepted_ref'],run['accepted_ref'])
        self.assertEqual(after['usage']['model_calls'],0)

    def test_preview_csrf_owner_version_options_and_missing_preview_guards(self):
        self.register();run=self.confirm(self.create());base='/api/runs/'+run['run_id'];request=self.design_request(run)
        self.assertEqual(self.client.post(base+'/media-preview',json=request).status_code,403)
        self.assertEqual(self.post(base+'/media-preview',dict(request,draft_ref='old')).status_code,409)
        self.assertEqual(self.post(base+'/media-preview',dict(request,content_hash='old')).status_code,409)
        self.assertEqual(self.post(base+'/media-preview',dict(request,template='unsafe')).status_code,400)
        self.assertEqual(self.post(base+'/media-preview',dict(request,options={'page_styles':{'999':{'size':'normal'}}})).status_code,400)
        self.assertEqual(self.post(base+'/media-preview',dict(request,options={'cover_image':'data:image/svg+xml;base64,PHN2Zz4='})).status_code,400)
        self.assertEqual(self.post(base+'/media-export',dict(request,kind='images')).status_code,400)
        self.post('/api/auth/logout',{});self.csrf=self.client.get('/api/session').json()['csrf'];self.register('other_card_user')
        self.assertEqual(self.post(base+'/media-preview',request).status_code,404)
        self.assertEqual(self.post(base+'/media-export',dict(request,kind='images',design_hash='0'*64)).status_code,404)

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
        for suffix in ['/media/capabilities', '/media-export?kind=images', '/media-export?kind=video', '/media-export?kind=complete']:
            response = self.client.get('/api/runs/' + run['run_id'] + suffix)
            self.assertEqual(response.status_code, 404, response.text)
            self.assertNotIn(run['drafts'][-1]['content']['body'], response.text)

    def test_unconfirmed_draft_and_unknown_kind_rejected(self):
        self.register()
        run = self.create()
        for kind in ('images', 'video', 'storyboard', 'complete'):
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
        for kind in ('images', 'video', 'storyboard', 'complete'):
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
                    elif kind == 'storyboard':
                        self.assertIn(' --> ', archive.read('subtitles.srt').decode())
                    else:
                        self.assertIn('images/01.png', archive.namelist())
                        self.assertIn('video/video.mp4', archive.namelist())
                        self.assertIn('使用说明.txt', archive.namelist())
                        evidence = json.loads(archive.read('execution-evidence.json'))
                        self.assertEqual(evidence['draft_ref'], run['accepted_ref'])
                        self.assertEqual(evidence['usage']['model_calls'], 0)
                        self.assertNotIn('owner', evidence)
                        self.assertNotIn('api_key', evidence)
        # Downloading is read-only: the accepted draft/version and paid ledger do not change.
        after = self.client.get(base).json()
        self.assertEqual(after['status_version'], run['status_version'])
        self.assertEqual(after['accepted_ref'], run['accepted_ref'])
        self.assertEqual(after['usage']['model_calls'], 0)


if __name__ == '__main__': unittest.main()

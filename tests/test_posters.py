"""Independent poster persistence: both SQLite and isolated real PostgreSQL."""
import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import zipfile
import hashlib
import unittest
from uuid import uuid4
from unittest.mock import patch, Mock
from PIL import Image
from backend import posters
from backend.contracts import DomainError
from backend.migrations import upgrade
from backend.store import Store
from tests.test_media_exports import fixture


def image_data(color='tan',fmt='PNG'):
    stream=BytesIO(); Image.new('RGB',(96,128),color).save(stream,format=fmt)
    return 'data:image/'+('jpeg' if fmt=='JPEG' else 'png')+';base64,'+base64.b64encode(stream.getvalue()).decode()


class PosterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'db.sqlite'); self.prepare()

    def prepare(self):
        upgrade(self.store); self.run=fixture('保持独立海报与原稿隔离')
        with self.store.connect() as db: db.execute('INSERT INTO runs(id,owner,payload) VALUES(?,?,?)',(self.run.run_id,self.run.owner_id,json.dumps(asdict(self.run))))
        self.assertEqual(posters.read(self.store,self.run.owner_id,self.run.run_id),{'state':None,'source_image':None,'source_name':None})
        self.state=self.action('init')['state']

    def data(self,action,**extras):
        return {'action':action,'expected_revision':getattr(self,'state',{}).get('revision',0),'draft_ref':self.run.accepted_ref,'content_hash':self.run.acceptance['content_hash'],'idempotency_key':uuid4().hex,**extras}

    def action(self,action,**extras):
        result=posters.mutate(self.store,self.run.owner_id,self.run.run_id,self.data(action,**extras)); self.state=result['state']; return result

    def export(self,**extras):
        data=self.data('export'); data.pop('action'); data.pop('idempotency_key')
        return posters.export(self.store,self.run.owner_id,self.run.run_id,{**data,**extras})

    def test_import_restore_undo_redo_accept_and_exact_export(self):
        self.action('import',image=image_data(fmt='JPEG'),brief='海报摘要，非完整正文',prompt='纸张与留白')
        first=self.state['current']; self.assertTrue(self.state['has_pending']); self.assertTrue(self.state['can_undo'])
        with self.assertRaises(DomainError): self.export()
        self.action('undo'); self.assertIsNone(self.state['current']); self.assertTrue(self.state['can_redo'])
        self.action('redo'); self.assertEqual(self.state['current'],first)
        self.action('accept'); raw,mime,name=self.export()
        self.assertEqual(raw,base64.b64decode(first['data_url'].split(',')[1])); self.assertEqual(mime,'image/png')
        fresh=Store(self.store.path); self.assertEqual(posters.read(fresh,self.run.owner_id,self.run.run_id)['state'],self.state)
        self.assertEqual(fresh.get(self.run.run_id,self.run.owner_id).drafts,self.run.drafts)

    def test_historical_multipage_payload_restore_history_and_exact_exports(self):
        self.action('import',image=image_data('red'))
        asset=self.state['current']; pages=[posters.normalize_image(image_data(color)) for color in ('red','blue','green')]
        asset.update(pages=pages,page_count=3,skill_id='baoyu-infographic')
        with self.store.connect() as db:
            db.execute('UPDATE poster_assets SET payload=? WHERE id=?',(json.dumps(asset),asset['id']))
        self.state=posters.read(self.store,self.run.owner_id,self.run.run_id)['state']
        self.assertEqual(self.state['current']['pages'],pages)
        with self.assertRaises(DomainError): self.export(format='zip')
        self.action('accept')
        for i,page in enumerate(pages):
            raw,mime,name=self.export(page_index=i)
            self.assertEqual(raw,base64.b64decode(page['data_url'].split(',')[1])); self.assertEqual(mime,'image/png')
        raw,mime,name=self.export(format='zip')
        self.assertEqual(mime,'application/zip')
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['page_count'],3)
            for i,page in enumerate(pages):
                expected=base64.b64decode(page['data_url'].split(',')[1])
                self.assertEqual(archive.read(f'{i+1:02d}.png'),expected)
                self.assertEqual(manifest['pages'][i]['sha256'],hashlib.sha256(expected).hexdigest())
        for extras in ({'page_index':-1},{'page_index':3},{'page_index':True},{'format':'mp4'},{'format':'zip','expected_revision':99}):
            with self.subTest(extras=extras),self.assertRaises(DomainError): self.export(**extras)
        data=self.data('export');data.pop('action');data.pop('idempotency_key')
        with self.assertRaises(DomainError): posters.export(self.store,'other',self.run.run_id,data)
        self.action('import',image=image_data('tan'))
        self.assertNotIn('pages',self.state['current'])
        self.action('undo');self.assertEqual(self.state['current']['pages'],pages)
        self.action('redo');self.assertNotIn('pages',self.state['current'])
        self.action('undo')
        with self.store.connect() as db:
            self.assertEqual(json.loads(db.execute('SELECT payload FROM poster_assets WHERE id=?',(asset['id'],)).fetchone()[0]),asset)
        self.assertEqual(posters.read(self.store,self.run.owner_id,self.run.run_id)['state']['current']['pages'],pages)

    def test_revision_owner_snapshot_and_idempotent_replay(self):
        data=self.data('import',image=image_data()); first=posters.mutate(self.store,self.run.owner_id,self.run.run_id,data)
        self.state=first['state']; self.action('import',image=image_data('blue'))
        self.assertEqual(posters.mutate(self.store,self.run.owner_id,self.run.run_id,data),first)
        for changes in ({'expected_revision':99,'idempotency_key':uuid4().hex},{'content_hash':'stale','idempotency_key':uuid4().hex},{'image':image_data('red')}):
            with self.assertRaises(DomainError): posters.mutate(self.store,self.run.owner_id,self.run.run_id,{**data,**changes})
        with self.assertRaises(DomainError): posters.read(self.store,'other',self.run.run_id)
        with self.assertRaises(DomainError): posters.mutate(self.store,'other',self.run.run_id,data)

    def test_invalid_media_is_atomic_and_animation_rejected(self):
        before=self.state
        for value in ('garbage','data:image/png;base64,AAAA','data:image/svg+xml;base64,AAAA'):
            with self.assertRaises(DomainError): self.action('import',image=value)
        with self.assertRaises(DomainError): self.action('import',image=image_data(),brief=['bad'])
        self.assertEqual(posters.read(self.store,self.run.owner_id,self.run.run_id)['state'],before)
        stream=BytesIO(); Image.new('RGB',(10,10),'red').save(stream,format='PNG',save_all=True,append_images=[Image.new('RGB',(10,10),'blue')],duration=100)
        with self.assertRaises(DomainError): self.action('import',image='data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode())

    def test_branch_truncates_redo_and_history_is_bounded_without_duplicate_bytes(self):
        for index in range(12): self.action('import',image=image_data(),brief=str(index))
        self.action('undo'); self.action('import',image=image_data('blue'))
        self.assertFalse(self.state['can_redo'])
        with self.store.connect() as db:
            payload=db.execute('SELECT payload FROM poster_sessions').fetchone()[0]
            self.assertLessEqual(len(json.loads(payload)['history']),10)
            self.assertNotIn('base64',payload)
            self.assertTrue(all('base64' not in row[0] for row in db.execute('SELECT response FROM poster_commands').fetchall()))

    def test_concurrent_same_revision_only_one_import_wins(self):
        requests=[self.data('import',image=image_data(color)) for color in ('red','blue')]
        def submit(data):
            try: return posters.mutate(self.store,self.run.owner_id,self.run.run_id,data)
            except DomainError as exc: return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(submit,requests))
        self.assertEqual(sum(isinstance(row,dict) for row in results),1)
        self.assertIn('VERSION_CONFLICT',results)


    def generation_data(self):
        data=self.data('generate',source_image=image_data(),brief='保留实拍与正文',style='zine'); data.pop('action'); return data

    def test_local_generation_once_replay_and_server_snapshot(self):
        renderer=Mock(return_value=image_data('blue')); data=self.generation_data()
        with patch('backend.poster_local.render',renderer):
            result=posters.generate(self.store,self.run.owner_id,self.run.run_id,data)
            replay=posters.generate(self.store,self.run.owner_id,self.run.run_id,data)
        self.assertEqual(result,replay); renderer.assert_called_once()
        self.assertEqual(renderer.call_args.args[1]['content_hash'],self.run.acceptance['content_hash'])
        self.assertEqual(result['state']['current']['source'],'local_composition')
        self.assertEqual(result['state']['current']['provider'],'local-pillow')
        with self.assertRaises(DomainError): self.action('import',image=image_data(),source='local_composition')
        with self.assertRaises(DomainError): posters.generate(self.store,'other',self.run.run_id,data)

    def test_local_generation_failure_no_retry_or_mutation(self):
        renderer=Mock(side_effect=RuntimeError('local failure')); data=self.generation_data(); before=self.state
        with patch('backend.poster_local.render',renderer):
            for _ in range(2):
                with self.assertRaises(DomainError): posters.generate(self.store,self.run.owner_id,self.run.run_id,data)
        renderer.assert_called_once()
        self.assertEqual(posters.read(self.store,self.run.owner_id,self.run.run_id)['state'],before)
        with self.store.connect() as db: self.assertEqual(db.execute('SELECT status FROM poster_generation_calls').fetchone()[0],'FAILED')

    def test_local_generation_late_result_never_overwrites_newer_edit(self):
        def render(*args):
            self.action('import',image=image_data('red')); return image_data('blue')
        with patch('backend.poster_local.render',render):
            with self.assertRaises(DomainError) as caught: posters.generate(self.store,self.run.owner_id,self.run.run_id,self.generation_data())
        self.assertEqual(caught.exception.code,'VERSION_CONFLICT')
        self.assertEqual(posters.read(self.store,self.run.owner_id,self.run.run_id)['state'],self.state)


    def insert_studio_source(self,run=None,owner=None,content_hash=None):
        run=run or self.run
        asset={'id':'original-a','role':'product','name':'我的实拍.png','data_url':image_data('red')}
        newest={'id':'original-b','role':'product','name':'另一张实拍.png','data_url':image_data('blue')}
        reference={'id':'reference','role':'reference','name':'参考.png','data_url':image_data('green')}
        payload={'current':{'options':{'studio':{'pages':{'0':{'image':{'asset_id':asset['id']}}}}}},'assets':[asset,newest,reference]}
        with self.store.connect() as db:
            db.execute('INSERT INTO studio_sessions(run_id,owner,draft_ref,content_hash,revision,payload) VALUES(?,?,?,?,?,?)',(run.run_id,owner or run.owner_id,run.accepted_ref,content_hash or run.acceptance['content_hash'],0,json.dumps(payload)))
        return asset,newest,payload

    def test_source_uses_same_draft_selected_original_and_never_preview(self):
        asset,newest,payload=self.insert_studio_source()
        response=posters.read(self.store,self.run.owner_id,self.run.run_id)
        self.assertEqual(response['source_image'],asset['data_url'])
        self.assertEqual(response['source_name'],asset['name'])
        data=self.data('init'); first=posters.mutate(self.store,self.run.owner_id,self.run.run_id,data)
        self.assertEqual(posters.mutate(self.store,self.run.owner_id,self.run.run_id,data)['source_image'],asset['data_url'])
        payload['current']['options']['studio']['pages']={}
        with self.store.connect() as db:
            db.execute('UPDATE studio_sessions SET payload=? WHERE run_id=?',(json.dumps(payload),self.run.run_id))
            saved=db.execute('SELECT payload FROM poster_sessions WHERE run_id=?',(self.run.run_id,)).fetchone()[0]
        self.assertNotIn('source_image',saved)
        self.assertEqual(posters.read(self.store,self.run.owner_id,self.run.run_id)['source_image'],newest['data_url'])

    def test_source_catalogue_requires_explicit_brand_model(self):
        mouse=fixture('罗技 M185 是已确认主题')
        with self.store.connect() as db: db.execute('INSERT INTO runs(id,owner,payload) VALUES(?,?,?)',(mouse.run_id,mouse.owner_id,json.dumps(asdict(mouse))))
        response=posters.read(self.store,mouse.owner_id,mouse.run_id)
        self.assertIsNone(response['state']); self.assertTrue(response['source_image'].startswith('data:image/jpeg;base64,'))
        self.assertIn('CC BY 4.0',response['source_name'])
        self.assertIsNone(posters.read(self.store,self.run.owner_id,self.run.run_id)['source_image'])

    def test_source_never_crosses_owner_snapshot_or_run(self):
        self.insert_studio_source(owner='other')
        self.assertIsNone(posters.read(self.store,self.run.owner_id,self.run.run_id)['source_image'])
        with self.store.connect() as db:
            db.execute('DELETE FROM studio_sessions WHERE run_id=?',(self.run.run_id,))
        self.insert_studio_source(content_hash='old-draft')
        self.assertIsNone(posters.read(self.store,self.run.owner_id,self.run.run_id)['source_image'])
        other=fixture()
        with self.store.connect() as db: db.execute('INSERT INTO runs(id,owner,payload) VALUES(?,?,?)',(other.run_id,other.owner_id,json.dumps(asdict(other))))
        self.insert_studio_source(run=other)
        self.assertIsNone(posters.read(self.store,self.run.owner_id,self.run.run_id)['source_image'])
        with self.assertRaises(DomainError): posters.read(self.store,'other',other.run_id)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'requires actual PostgreSQL')
class PostgresPosterTests(PosterTests):
    def setUp(self):
        import psycopg
        self.base=os.environ['TEST_DATABASE_URL']; self.schema='youji_poster_'+uuid4().hex
        with psycopg.connect(self.base,autocommit=True) as db: db.execute('CREATE SCHEMA '+self.schema)
        self.addCleanup(self.drop_schema)
        self.store=Store(self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema); self.prepare()

    def drop_schema(self):
        import psycopg
        with psycopg.connect(self.base,autocommit=True) as db: db.execute('DROP SCHEMA '+self.schema+' CASCADE')


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'requires actual PostgreSQL')
class PosterHttpTests(unittest.TestCase):
    drop_schema=PostgresPosterTests.drop_schema
    prepare=PosterTests.prepare
    data=PosterTests.data
    action=PosterTests.action

    def setUp(self):
        from fastapi.testclient import TestClient
        from backend.api import create_app
        from backend.provider import Config
        PostgresPosterTests.setUp(self)
        self.client=TestClient(create_app(self.store,Config(),origin='http://testserver',invite=''))
        self.addCleanup(self.client.close)
        csrf=self.client.get('/api/session').json()['csrf']
        response=self.client.post('/api/auth/register',json={'username':'poster_tester','password':'Poster-Tests-2026'},headers={'Origin':'http://testserver','X-CSRF-Token':csrf})
        self.assertEqual(response.status_code,200,response.text)
        self.headers={'Origin':'http://testserver','X-CSRF-Token':response.json()['csrf']}
        self.run.owner_id=response.json()['user']['id']
        with self.store.connect() as db:
            db.execute('DELETE FROM poster_sessions WHERE run_id=?',(self.run.run_id,))
            db.execute('UPDATE runs SET owner=?,payload=? WHERE id=?',(self.run.owner_id,json.dumps(asdict(self.run)),self.run.run_id))
        self.url='/api/runs/'+self.run.run_id+'/poster'

    def test_authenticated_import_download_and_csrf(self):
        self.assertEqual(self.client.get(self.url).json(),{'state':None,'source_image':None,'source_name':None})
        response=self.client.post(self.url,json=self.data('init'),headers=self.headers)
        self.assertEqual(response.status_code,200,response.text); self.state=response.json()['state']
        data=self.data('import',image=image_data())
        self.assertEqual(self.client.post(self.url,json=data).status_code,403)
        response=self.client.post(self.url,json=data,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text); self.state=response.json()['state']
        response=self.client.post(self.url,json=self.data('accept'),headers=self.headers)
        self.assertEqual(response.status_code,200,response.text); self.state=response.json()['state']
        data=self.data('export'); data.pop('action'); data.pop('idempotency_key')
        response=self.client.post(self.url+'/export',json=data,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.content,base64.b64decode(self.state['accepted']['data_url'].split(',')[1]))
        self.assertEqual(response.headers['content-type'],'image/png')

    def test_poster_static_assets_are_served(self):
        for name,mime in (('posters.js','javascript'),('posters.css','text/css'),('poster_generation.js','javascript')):
            response=self.client.get('/'+name)
            self.assertEqual(response.status_code,200,name)
            self.assertIn(mime,response.headers['content-type'])

    def test_local_generate_http_uses_confirmed_content(self):
        response=self.client.post(self.url,json=self.data('init'),headers=self.headers)
        self.assertEqual(response.status_code,200,response.text); self.state=response.json()['state']
        data=self.data('generate',source_image=image_data(),brief='纸感，蓝色，米色背景',style='zine'); data.pop('action')
        response=self.client.post(self.url+'/generate',json=data,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        current=response.json()['state']['current']
        self.assertEqual(current['source'],'local_composition')
        self.assertEqual(current['content_scope'],'confirmed_copy_composition')
        self.assertGreaterEqual(current['height'],1440)
        replay=self.client.post(self.url+'/generate',json=data,headers=self.headers)
        self.assertEqual(replay.json(),response.json())

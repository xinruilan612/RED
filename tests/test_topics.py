"""Account adaptation integration; encoder stub tests routing, not model quality."""
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
from datetime import datetime,timezone,timedelta
from fastapi.testclient import TestClient
from backend.api import create_app
from backend.provider import Config
from backend.store import Store
from backend.topics import history_rows,config_for

class TopicTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'db.sqlite');self.start()
    def start(self):
        self.app=create_app(self.store,Config(),origin='http://testserver',invite='');self.client=TestClient(self.app)
        self.csrf=self.client.get('/api/session').json()['csrf']
        r=self.post('/api/auth/register',{'username':'topic_tester','password':'TestingPass123'})
        self.assertEqual(r.status_code,200,r.text);self.csrf=r.json()['csrf']
        self.owner=self.app.state.auth.session(self.client.cookies.get('youji_session'))['owner']
        self.ops=self.app.state.service.operations;self.identity=self.ops.read(self.owner)['accounts'][0]['id'];self.seen=[]
        def encoder(texts,images):
            self.seen.append((texts,images))
            return dict(model='OFA-Sys/chinese-clip-vit-base-patch16',text_vectors=[[1.,0.] if '摄影' in t else [0.,1.] for t in texts],image_vectors=[[1.,0.] for _ in images])
        self.app.state.topics.encoder=encoder
    def tearDown(self): self.client.close();self.temp.cleanup()
    def post(self,url,data):return self.client.post(url,json=data,headers={'Origin':'http://testserver','X-CSRF-Token':self.csrf})
    def read(self):return self.client.get('/api/topics',params={'account_id':self.identity}).json()
    def configure(self,position='摄影教程'):
        r=self.read();r['config'].update(positioning=position,audience='大学生')
        response=self.post('/api/topics/config',dict(account_id=self.identity,version=r['version'],config=r['config']))
        self.assertEqual(response.status_code,200,response.text);return response.json()
    def command(self,action,payload,owner=None):
        owner=owner or self.owner
        return self.ops.command(owner,dict(action=action,payload=payload,version=self.ops.read(owner)['version'],key=str(uuid4())))
    def publication(self,owner=None):
        owner=owner or self.owner;identity=self.ops.read(owner)['accounts'][0]['id']
        state=self.command('import_post',dict(account_id=identity,title='摄影历史作品',body='真实历史正文',url='https://www.xiaohongshu.com/explore/'+uuid4().hex,published_at=(datetime.now(timezone.utc)-timedelta(days=8)).isoformat(),format='image_text',pillar='摄影',traffic='organic'),owner)
        return state['publications'][0]
    def test_public_samples_are_encoded_but_never_personal_labels(self):
        r=self.configure()
        imported=self.post('/api/topics/public/import',dict(account_id=self.identity,version=r['version'],samples=[dict(url='https://www.xiaohongshu.com/explore/12345678',title='摄影构图参考',body='公开样本测试',counts={'likes':200})]))
        self.assertEqual(imported.status_code,200,imported.text)
        result=self.post('/api/topics/evaluate',dict(account_id=self.identity,version=imported.json()['version'],candidates=[dict(id='a',title='摄影构图')])).json()
        self.assertEqual(result['public_sample_count'],1)
        self.assertFalse(result['public_prediction_available'])
        row=result['candidates'][0]
        self.assertIsNone(row['estimated_value'])
        self.assertEqual(row['public_references'][0]['likes'],200)
        self.assertIsNone(row['public_references'][0]['saves'])
        self.assertTrue(any('公开样本测试' in text for text in self.seen[-1][0]))
        self.assertEqual(self.ops.read(self.owner)['publications'],[])
        other=self.ops.read('other')['accounts'][0]['id']
        self.assertEqual(self.client.get('/api/topics/public',params={'account_id':other}).status_code,404)
        self.assertEqual(self.client.post('/api/topics/public/import',json={}).status_code,403)

    def test_public_library_switch_filters_encoder_and_restores_saved_references(self):
        r=self.configure('摄影')
        imported=self.post('/api/topics/public/import',dict(account_id=self.identity,version=r['version'],samples=[dict(url='https://www.xiaohongshu.com/explore/12345678',title='摄影专属参考',body='摄影证据')]))
        self.assertEqual(imported.status_code,200,imported.text)
        r=self.configure('烹饪')
        library=self.client.get('/api/topics/public',params={'account_id':self.identity}).json()
        self.assertEqual(library['positioning'],'烹饪');self.assertEqual(library['samples'],[]);self.assertEqual(library['archived_count'],1)
        result=self.post('/api/topics/evaluate',dict(account_id=self.identity,version=r['version'],candidates=[dict(id='food',title='烹饪')])).json()
        self.assertEqual(result['public_sample_count'],0)
        self.assertFalse(any('摄影专属参考' in t for t in self.seen[-1][0]))
        self.configure('摄影')
        library=self.client.get('/api/topics/public',params={'account_id':self.identity}).json()
        self.assertEqual(len(library['samples']),1);self.assertEqual(library['archived_count'],0)

    def test_encoder_batches_large_combined_pools_and_keeps_long_text_tail(self):
        calls=[]
        def bounded(texts,images):
            self.assertLessEqual(len(texts),128)
            self.assertTrue(all(len(t)<=10000 for t in texts))
            calls.append((texts,images))
            return dict(model='test',text_vectors=[[1.,0.] if '尾部' not in t else [0.,1.] for t in texts],image_vectors=[[1.,0.] for _ in images])
        self.app.state.topics.encoder=bounded
        result=self.app.state.topics.encode(['前'*11000+'尾部']+['公开正文']*199,['image'])
        self.assertEqual(len(result['text_vectors']),200)
        self.assertGreater(result['text_vectors'][0][1],0)
        self.assertEqual(result['image_vectors'],[[1.,0.]])
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[1][1],[])

    def test_config_updates_live_profile_and_persists(self):
        first=self.configure();self.assertEqual(self.ops.read(self.owner)['accounts'][0]['profile']['positioning'],'摄影教程')
        self.configure('校园收纳');self.assertEqual(self.read()['config']['positioning'],'校园收纳')
        self.assertGreater(self.read()['account_revision'],first['account_revision'])
    def test_owner_isolation_auth_and_csrf(self):
        other=self.ops.read('other')['accounts'][0]['id']
        self.assertEqual(self.client.get('/api/topics',params={'account_id':other}).status_code,404)
        self.assertEqual(TestClient(self.app).get('/api/topics',params={'account_id':self.identity}).status_code,401)
        self.assertEqual(self.client.post('/api/topics/config',json={}).status_code,403)
    def test_cold_start_dynamic_ranking_without_heat(self):
        r=self.configure()
        response=self.post('/api/topics/evaluate',dict(account_id=self.identity,version=r['version'],candidates=[dict(id='a',title='摄影构图'),dict(id='b',title='宿舍收纳')]))
        self.assertEqual(response.status_code,200,response.text);result=response.json()
        self.assertEqual(result['status'],'matching_only');self.assertEqual(result['candidates'][0]['id'],'a')
        self.assertTrue(all(c['estimated_value'] is None for c in result['candidates']))
        self.assertIn(self.identity,self.ops.read(self.owner)['topic_results'])
        r=self.configure('宿舍收纳')
        response=self.post('/api/topics/evaluate',dict(account_id=self.identity,version=r['version'],candidates=[dict(id='a',title='摄影构图'),dict(id='b',title='宿舍收纳')]))
        self.assertEqual(response.json()['candidates'][0]['id'],'b')
    def test_image_stored_as_vector_not_raw_and_cross_owner_rejected(self):
        p=self.publication();r=self.read()
        data=dict(account_id=self.identity,version=r['version'],publication_id=p['id'],image='test-encoder-fixture')
        response=self.post('/api/topics/history-image',data);self.assertEqual(response.status_code,200,response.text)
        saved=self.ops.read(self.owner)['topic_images'][p['id']];self.assertNotIn('image',saved);self.assertEqual(saved['vector'],[1.,0.])
        other=self.publication('other');data.update(publication_id=other['id'],version=self.read()['version'])
        self.assertEqual(self.post('/api/topics/history-image',data).status_code,404)
    def test_stale_version_rejected_before_encoder(self):
        r=self.configure();self.configure('换定位')
        response=self.post('/api/topics/evaluate',dict(account_id=self.identity,version=r['version'],candidates=[dict(id='a',title='摄影')]))
        self.assertEqual(response.status_code,409);self.assertEqual(self.seen,[])
    def test_inference_race_rejects_outdated_result(self):
        r=self.configure();encoder=self.app.state.topics.encoder
        def racing(texts,images):
            self.configure('新的定位');return encoder(texts,images)
        self.app.state.topics.encoder=racing
        response=self.post('/api/topics/evaluate',dict(account_id=self.identity,version=r['version'],candidates=[dict(id='a',title='摄影')]))
        self.assertEqual(response.status_code,409);self.assertNotIn(self.identity,self.ops.read(self.owner).get('topic_results',{}))
    def test_untrusted_clients_cannot_inject_vectors_or_results(self):
        for action in ('topic_image','topic_result'):
            response=self.post('/api/operations',dict(action=action,payload={},version=self.read()['version'],key=str(uuid4())))
            self.assertEqual(response.status_code,400)
    def test_window_missing_metric_and_simulation_boundaries(self):
        p=self.publication();state=self.ops.read(self.owner);account=state['accounts'][0];config=config_for(state,account)
        self.assertFalse(history_rows(state,account,config)[0]['eligible'])
        state['metrics'].append(dict(publication_id=p['id'],window='72h',observed_at=(datetime.fromisoformat(p['published_at'])+timedelta(hours=93)).isoformat(),source_type='manual',values={'views':19}))
        row=history_rows(state,account,config)[0];self.assertIsNone(row['value']);self.assertIn('不一致',row['exclusion'])
        state['metrics'][-1]['observed_at']=(datetime.fromisoformat(p['published_at'])+timedelta(hours=72)).isoformat()
        self.assertEqual(history_rows(state,account,config)[0]['value'],19)
        state['publications'][0]['provenance']='simulation';self.assertEqual(history_rows(state,account,config),[])
    def test_skapp_missing_never_exposes_old_kernel_estimate(self):
        from unittest.mock import patch
        r=self.configure()
        original=__import__('backend.topic_ranking',fromlist=['evaluate']).evaluate
        def old(*args):
            value=original(*args)
            value['candidates'][0]['estimated_value']=9999
            value['status']='experimental_prediction'
            return value
        with patch('backend.topic_ranking.evaluate',side_effect=old):
            result=self.post('/api/topics/evaluate',dict(account_id=self.identity,version=r['version'],candidates=[dict(id='a',title='摄影')])).json()
        self.assertEqual(result['status'],'matching_only')
        self.assertIsNone(result['candidates'][0]['estimated_value'])
        self.assertFalse(result['validation']['gate'])
        self.assertEqual(result['skapp']['status'],'not_trained')

    def test_only_skapp_prediction_is_exposed(self):
        from unittest.mock import patch
        r=self.configure()
        with patch('backend.skapp_personal.predict',return_value=dict(available=True,status='ready',method='upstream_skapp_shared',predictions=[dict(id='a',predicted_value=42)],message='原模型测试替身')):
            result=self.post('/api/topics/evaluate',dict(account_id=self.identity,version=r['version'],candidates=[dict(id='a',title='摄影')])).json()
        self.assertEqual(result['candidates'][0]['estimated_value'],42)
        self.assertEqual(result['method'],'upstream_skapp_shared')

    def test_training_snapshot_invalidates_only_relevant_changes(self):
        import copy
        from backend.topics import training_history_digest
        p=self.publication();state=self.ops.read(self.owner);account=state['accounts'][0];config=config_for(state,account)
        before=training_history_digest(state,account,config)
        changed=copy.deepcopy(state);changed['version']+=1;changed['topic_results']={'anything':{}}
        self.assertEqual(before,training_history_digest(changed,account,config))
        changed['publications'][0]['traffic']='paid'
        self.assertNotEqual(before,training_history_digest(changed,account,config))
        changed=copy.deepcopy(state);changed['topic_images']={p['id']:{'model':'new','vector':[1]}}
        self.assertNotEqual(before,training_history_digest(changed,account,config))
        self.assertNotEqual(before,training_history_digest(state,account,dict(config,positioning='新方向')))

    def test_training_export_empty_and_access_boundaries(self):
        r=self.configure()
        result=self.post('/api/topics/training-data',dict(account_id=self.identity,version=r['version']))
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['records'],[])
        self.assertEqual(result.json()['target_metric'],'views')
        self.assertEqual(result.json()['minimum_training_records'],100)
        other=self.ops.read('other')['accounts'][0]['id']
        self.assertEqual(self.post('/api/topics/training-data',dict(account_id=other,version=r['version'])).status_code,404)
        self.assertEqual(self.client.post('/api/topics/training-data',json={}).status_code,403)

    def test_bad_config_and_duplicates_fail(self):
        r=self.configure();bad=dict(r['config'],text_weight=-1)
        self.assertEqual(self.post('/api/topics/config',dict(account_id=self.identity,version=r['version'],config=bad)).status_code,400)
        self.assertEqual(self.post('/api/topics/evaluate',dict(account_id=self.identity,version=r['version'],candidates=[dict(id='x',title='a'),dict(id='x',title='b')])).status_code,400)

@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'PostgreSQL URL required')
class PostgresTopicTests(TopicTests):
    def setUp(self):
        import psycopg
        self.temp=tempfile.TemporaryDirectory();self.schema='topics_'+uuid4().hex;self.base=os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('CREATE SCHEMA '+self.schema)
        self.store=Store(self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema);self.start()
    def tearDown(self):
        import psycopg
        super().tearDown()
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('DROP SCHEMA '+self.schema+' CASCADE')

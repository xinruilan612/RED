import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from backend.store import Store
from backend.migrations import upgrade
from backend.operations import Operations
from backend.contracts import DomainError
from backend.xhs_research import XHSResearch
from backend.research_jobs import ResearchJobs


class XHSResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'test.sqlite');upgrade(self.store)
        self.account=Operations(self.store).read('owner')['accounts'][0]['id']
        with self.store.connect() as db:
            db.execute("INSERT INTO xhs_sync_links(owner,account_id,source_id,bridge_port,interval_s,enabled,status,next_at) VALUES(?,?,?,?,?,1,'ready',0)",('owner',self.account,'person',18061,900))
        self.calls=[];test=self
        class Client:
            def __init__(self,port):pass
            def identity(self):return {'id':'person'}
            def search(self,query):
                test.calls.append(query)
                return {'feeds':[{'id':str(i),'xsecToken':'private-token'} for i in range(6)]}
            def request(self,path,data):
                test.calls.append(data['feed_id'])
                return {'note':{'noteId':data['feed_id'],'title':'合成护肤案例','desc':'先说明适用情境，再列出使用步骤与限制，不许宣称人人有效。'+data['feed_id'],'time':1767225600000,'interactInfo':{'likedCount':'1.2万','collectedCount':'300'},'user':{'nickname':'合成作者'}}}
        self.client=Client

    def test_bounds_no_tokens_no_fake_transcript_or_rounded_metrics(self):
        notes,attempts=XHSResearch(self.store,self.client).collect('owner',self.account,['护肤','保湿'])
        self.assertEqual(len(notes),3);self.assertEqual(len(self.calls),5)
        self.assertNotIn('private-token',str(notes)+str(attempts))
        self.assertIsNone(notes[0]['metrics']['likes']);self.assertIsNone(notes[0]['metrics']['views'])
        self.assertEqual(notes[0]['metrics']['favorites'],300)
        self.assertEqual(notes[0]['content_kind'],'text');self.assertIn('未读取音轨',notes[0]['text'])

    def test_public_style_thresholds_and_provenance(self):
        search=self.client.search
        def filtered(client,query,filters=None):
            self.assertEqual(filters['note_type'],'不限')
            return search(client,query)
        selection={'min_likes':100,'min_favorites':50,'sort_by':'favorites'}
        with patch.object(self.client,'search',filtered):
            notes,_=XHSResearch(self.store,self.client).collect('owner',self.account,['护肤'],style_filters=selection)
        self.assertEqual(len(notes),3)
        self.assertTrue(notes[0]['_provenance']['style_library_eligible'])
        self.assertEqual(notes[0]['_provenance']['visibility'],'public')
        self.assertIsNone(notes[0]['metrics']['likes'])
        selection['min_favorites']=1000
        with patch.object(self.client,'search',filtered):
            notes,_=XHSResearch(self.store,self.client).collect('owner',self.account,['护肤'],style_filters=selection)
        self.assertEqual(notes,[])

    def test_style_job_saves_eligible_case_and_rejects_invalid_filter(self):
        data=dict(account_id=self.account,queries=['护肤'],provider='xhs_local',targets=['xiaohongshu'],evidence_role='expression_reference',permission_confirmed=True,key='style',style_filters={'min_likes':100,'min_favorites':50,'sort_by':'likes'})
        jobs=ResearchJobs(self.store)
        data['style_filters']['min_likes']=0
        with self.assertRaises(DomainError):jobs.create('owner',data)
        data['style_filters']['min_likes']=100
        job=jobs.create('owner',data);search=self.client.search
        with patch('backend.xhs_research.LocalResearchClient',self.client),patch.object(self.client,'search',lambda c,q,filters=None:search(c,q)):
            jobs.once()
        self.assertEqual(jobs.get('owner',job['id'])['status'],'done')
        case=jobs.cases.list('owner',self.account)[0]['metadata']['research_case']
        self.assertEqual(case['source_method'],'local_browser_public_note')
        self.assertTrue(case['provenance']['style_library_eligible'])

    def test_owner_pause_and_identity_fail_closed(self):
        with self.assertRaises(DomainError):XHSResearch(self.store,self.client).connection('other',self.account)
        with self.store.connect() as db:db.execute('UPDATE xhs_sync_links SET enabled=0')
        with self.assertRaises(DomainError):XHSResearch(self.store,self.client).collect('owner',self.account,['护肤'])
        self.assertEqual(self.calls,[])

    def test_job_case_export_and_cancellation(self):
        jobs=ResearchJobs(self.store)
        data=dict(account_id=self.account,queries=['护肤'],provider='xhs_local',targets=['xiaohongshu'],evidence_role='expression_reference',permission_confirmed=True,key='one')
        job=jobs.create('owner',data)
        with patch('backend.xhs_research.LocalResearchClient',self.client):jobs.once()
        result=jobs.get('owner',job['id']);self.assertEqual(result['status'],'done')
        self.assertEqual(len(result['documents']),3)
        report=jobs.export('owner',job['id']);self.assertEqual(report['count'],3)
        self.assertIn('没有下载',report['content']);self.assertNotIn('private-token',str(result)+str(report))
        for doc in jobs.cases.list('owner',self.account):
            self.assertTrue(doc['metadata']['retrieval_eligible'])
            self.assertEqual(doc['metadata']['evidence_role'],'expression_reference')
        data['key']='two';job=jobs.create('owner',data)
        def stop():jobs.cancel('owner',job['id']);raise DomainError('RESEARCH_STOPPED','stop')
        with patch('backend.xhs_research.XHSResearch.collect',side_effect=lambda *a,**k:stop()):jobs.once()
        self.assertEqual(jobs.get('owner',job['id'])['status'],'cancelled')
        self.assertEqual(len(jobs.cases.list('owner',self.account)),3)

    def test_reject_fact_scope(self):
        jobs=ResearchJobs(self.store)
        data=dict(account_id=self.account,queries=['护肤'],provider='xhs_local',targets=['xiaohongshu'],evidence_role='product_fact',permission_confirmed=True,key='one')
        with self.assertRaises(DomainError):jobs.create('owner',data)

    def test_empty_descriptions_still_consume_detail_budget(self):
        original=self.client.request
        def empty(client,path,data):
            result=original(client,path,data);result['note']['desc']='';return result
        with patch.object(self.client,'request',empty):
            notes,_=XHSResearch(self.store,self.client).collect('owner',self.account,['护肤','保湿'])
        self.assertEqual(notes,[])
        self.assertEqual(len(self.calls),5)

    def research_job(self,jobs,key):
        return jobs.create('owner',dict(account_id=self.account,queries=['护肤'],provider='xhs_local',targets=['xiaohongshu'],evidence_role='expression_reference',permission_confirmed=True,key=key))

    def test_repeat_semantics_reuses_version_and_keeps_job_observation(self):
        jobs=ResearchJobs(self.store)
        first=self.research_job(jobs,'first')
        with patch('backend.xhs_research.LocalResearchClient',self.client):jobs.once()
        original=jobs.get('owner',first['id'])
        second=self.research_job(jobs,'second')
        with patch('backend.xhs_research.LocalResearchClient',self.client):jobs.once()
        repeated=jobs.get('owner',second['id'])
        self.assertEqual(repeated['status'],'done')
        self.assertEqual([i['version'] for i in repeated['items']],[1,1,1])
        self.assertEqual(original['document_ids'],repeated['document_ids'])
        self.assertTrue(all(i['observed_at'] for i in repeated['items']))
        self.assertGreater(repeated['items'][0]['observed_at'],original['items'][0]['observed_at'])
        self.assertEqual([d['version'] for d in jobs.cases.list('owner',self.account)],[1,1,1])

    def test_changed_metrics_or_content_create_new_versions(self):
        jobs=ResearchJobs(self.store);first=self.research_job(jobs,'first')
        with patch('backend.xhs_research.LocalResearchClient',self.client):jobs.once()
        original=jobs.get('owner',first['id']);request=self.client.request
        def changed(client,path,data):
            value=request(client,path,data)
            if data['feed_id']=='0':value['note']['interactInfo']['collectedCount']='301'
            if data['feed_id']=='1':value['note']['desc']+='新增正文'
            return value
        second=self.research_job(jobs,'second')
        with patch('backend.xhs_research.LocalResearchClient',self.client),patch.object(self.client,'request',changed):jobs.once()
        revised=jobs.get('owner',second['id'])
        self.assertEqual([i['version'] for i in revised['items']],[2,2,1])
        self.assertEqual([i['version'] for i in jobs.get('owner',first['id'])['items']],[1,1,1])
        self.assertEqual(jobs.cases.knowledge.get_version('owner',self.account,original['items'][0]['document_id'],1)['metadata']['research_case']['metrics']['favorites'],300)

    def test_pause_during_final_identity_saves_nothing(self):
        jobs=ResearchJobs(self.store);job=self.research_job(jobs,'pause');calls=[]
        def identity(client):
            calls.append(True)
            if len(calls)==2:
                with self.store.connect() as db:db.execute('UPDATE xhs_sync_links SET enabled=0')
            return {'id':'person'}
        with patch('backend.xhs_research.LocalResearchClient',self.client),patch.object(self.client,'identity',identity):jobs.once()
        result=jobs.get('owner',job['id']);self.assertEqual(result['error'],'XHS_STOPPED');self.assertEqual(result['document_ids'],[])
        self.assertEqual(jobs.cases.list('owner',self.account),[])

    def test_pause_immediately_before_save_is_transactionally_fenced(self):
        jobs=ResearchJobs(self.store);job=self.research_job(jobs,'pause');save=jobs.cases.save
        def pause(*args,**kwargs):
            with self.store.connect() as db:db.execute('UPDATE xhs_sync_links SET enabled=0')
            return save(*args,**kwargs)
        with patch('backend.xhs_research.LocalResearchClient',self.client),patch.object(jobs.cases,'save',pause):jobs.once()
        result=jobs.get('owner',job['id']);self.assertEqual(result['error'],'XHS_STOPPED');self.assertEqual(result['document_ids'],[])
        self.assertEqual(jobs.cases.list('owner',self.account),[])

    def test_binding_change_immediately_before_reuse_is_fenced(self):
        jobs=ResearchJobs(self.store);self.research_job(jobs,'first')
        with patch('backend.xhs_research.LocalResearchClient',self.client):jobs.once()
        job=self.research_job(jobs,'second');same=jobs._same_xhs_case
        def changed(*args):
            with self.store.connect() as db:db.execute("UPDATE xhs_sync_links SET source_id='different'")
            return same(*args)
        with patch('backend.xhs_research.LocalResearchClient',self.client),patch.object(jobs,'_same_xhs_case',changed):jobs.once()
        result=jobs.get('owner',job['id']);self.assertEqual(result['error'],'XHS_IDENTITY_CHANGED');self.assertEqual(result['document_ids'],[])
        self.assertEqual([d['version'] for d in jobs.cases.list('owner',self.account)],[1,1,1])


@unittest.skipUnless(__import__('os').environ.get('TEST_DATABASE_URL'),'requires actual PostgreSQL')
class PostgresXHSResearchTests(XHSResearchTests):
    def setUp(self):
        import os
        import psycopg
        from uuid import uuid4
        super().setUp()
        base=os.environ['TEST_DATABASE_URL'];schema='youji_xhs_research_'+uuid4().hex
        with psycopg.connect(base,autocommit=True) as db:db.execute('CREATE SCHEMA '+schema)
        def cleanup():
            with psycopg.connect(base,autocommit=True) as db:db.execute('DROP SCHEMA '+schema+' CASCADE')
        self.addCleanup(cleanup)
        self.store=Store(base+('&' if '?' in base else '?')+'options=-csearch_path%3D'+schema);upgrade(self.store)
        self.account=Operations(self.store).read('owner')['accounts'][0]['id']
        with self.store.connect() as db:
            db.execute("INSERT INTO xhs_sync_links(owner,account_id,source_id,bridge_port,interval_s,enabled,status,next_at) VALUES(?,?,?,?,?,1,'ready',0)",('owner',self.account,'person',18061,900))

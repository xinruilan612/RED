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

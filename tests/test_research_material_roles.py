"""Real temporary SQL integration, synthetic public pages, no model/network calls."""
import tempfile
import unittest
from pathlib import Path

from backend.knowledge import Knowledge
from backend.live import messages_for
from backend.operations import Operations
from backend.provider import Config
from backend.research_cases import ResearchCases
from backend.research_jobs import ResearchJobs
from backend.service import Service
from backend.store import Store
from test_original_retrieval import RecordingVectors


class ResearchMaterialRolesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name)/'roles.sqlite')
        self.owner = 'roles-owner'
        self.service = Service(self.store, Config())
        self.account = Operations(self.store).read(self.owner)['accounts'][0]['id']
        self.kb = Knowledge(self.store, RecordingVectors(), use_configured_embeddings=False)
        self.service.knowledge = self.kb
        self.cases = ResearchCases(self.store)
        self.target = {'domains':['photography'], 'channel':'xiaohongshu', 'format':'note'}
        self.text = '摄影相机参考：开篇用一个拍摄问题，分段解释构图与节奏，结尾邀请讨论。A1相机重量为300克。'

    def tearDown(self):
        self.temp.cleanup()

    def save(self, role, kind='text'):
        return self.cases.save(self.owner, {
            'account_id':self.account, 'title':'A1摄影相机参考',
            'text':self.text, 'source_url':'https://example.com/a1',
            'platform':'public_web', 'content_kind':kind,
            'evidence_role':role, 'permission_confirmed':True})

    def create_run(self):
        result = self.service.create(self.owner, {
            'mode':'simulation', 'topic':'A1摄影相机参考', 'audience':'摄影初学者',
            'tone':'清楚', 'material':'', 'scenario':'standard', 'allow_hypothesis':False,
            'creation':self.target, 'knowledge':{'enabled':True,'automatic_references':True},
            'operations':{'account_id':self.account,'platform':'xiaohongshu','account':'我的账号'}})
        run = self.store.get(result['run_id'], self.owner)
        # Review needs an existing draft; this in-memory fixture invokes no model.
        run.drafts = [{'content':{'selected_title':'摄影参考','body':'拍摄构图参考。','cta':'分享构图思路','tags':[]}}]
        return run

    def test_material_ingestion_then_automatic_fact_retrieval_without_document_selection(self):
        doc = self.save('product_fact')
        run = self.create_run()
        facts = run.context['creation_retrieval']['groups']['facts']
        self.assertEqual([doc['id']], [s['document_id'] for s in facts])
        self.assertEqual([],run.context['creation_retrieval']['groups']['examples'])
        for stage in ('audience','research','strategy','outline','hook','title','body','review'):
            with self.subTest(stage=stage):
                _, data = messages_for(run, stage)
                self.assertEqual(self.text,data['materials'][0]['text'])
                self.assertEqual([],data['creation_retrieval']['examples'])

    def test_generic_public_writing_reference_reaches_every_role_but_never_fact_materials(self):
        doc = self.save('expression_reference')
        self.assertEqual('any',doc['metadata']['classification']['channel'])
        self.assertEqual('any',doc['metadata']['classification']['format'])
        run = self.create_run()
        for stage in ('audience','research','strategy','outline','hook','title','body','review'):
            with self.subTest(stage=stage):
                messages, data = messages_for(run,stage)
                self.assertEqual([doc['id']],[s['document_id'] for s in data['creation_retrieval']['examples']])
                self.assertEqual(self.text,data['creation_retrieval']['examples'][0]['text'])
                self.assertEqual([],data['materials'])
                self.assertIn('不复制独特句子',messages[0]['content'])
                self.assertIn('methods/examples绝不能用作本题产品事实依据',messages[0]['content'])

    def test_saved_unread_lead_is_visible_in_library_and_excluded_from_all_retrieval(self):
        doc = self.save('expression_reference','lead')
        self.assertFalse(doc['metadata']['retrieval_eligible'])
        self.assertEqual('lead',doc['metadata']['research_case']['content_kind'])
        self.assertEqual(doc['id'],self.kb.list(self.owner,self.account)[0]['id'])
        grouped = self.kb.grouped_retrieve(self.owner,self.account,'A1摄影相机参考',self.target)
        self.assertEqual([],grouped['sources'])

    def test_unknown_interaction_metrics_do_not_become_high_performance_claim(self):
        doc = self.save('expression_reference')
        case = doc['metadata']['research_case']
        self.assertTrue(all(v is None for v in case['metrics'].values()))
        self.assertEqual('insufficient',case['assessment']['status'])
        self.assertIsNone(case['assessment']['known_interactions'])
        self.assertIn('不是同类对照',case['assessment']['limitation'])

    def public_search(self):
        text = self.text
        class Searcher:
            def search(self, owner, query, provider, targets):
                return {'results':[{'title':'A1摄影相机参考','url':'https://example.com/a1'}]}
        def reader(url):
            return {'title':'A1摄影相机参考','url':url,'text':text,
                    'fetched_at':'2026-01-01T00:00:00+00:00','verification':'公开正文'}
        jobs = ResearchJobs(self.store,searcher=Searcher(),reader=reader)
        job = jobs.create(self.owner, {'account_id':self.account,'queries':['A1摄影相机参考'],
            'provider':'bing','targets':['web'],'evidence_role':'expression_reference',
            'permission_confirmed':True,'confirmation_required':True,'key':'search'})
        jobs.once()
        return jobs,jobs.get(self.owner,job['id'])

    def test_confirmation_purpose_material_controls_real_saved_role_and_fact_retrieval(self):
        jobs,job = self.public_search()
        jobs.confirm(self.owner,job['id'],{'candidate_ids':[job['candidates'][0]['id']],
            'purpose':'product_fact','key':'material-confirmation'})
        doc = self.kb.get(self.owner,self.account,self.kb.list(self.owner,self.account)[0]['id'])
        self.assertEqual('product_fact',doc['metadata']['evidence_role'])
        self.assertEqual('fact',doc['metadata']['classification']['material_type'])
        run = self.create_run()
        self.assertEqual([doc['id']],[s['document_id'] for s in run.context['creation_retrieval']['groups']['facts']])

    def test_confirmation_purpose_reference_controls_real_saved_role_and_examples(self):
        jobs,job = self.public_search()
        jobs.confirm(self.owner,job['id'],{'candidate_ids':[job['candidates'][0]['id']],
            'purpose':'expression_reference','key':'reference-confirmation'})
        run = self.create_run()
        grouped = run.context['creation_retrieval']['groups']
        self.assertEqual(1,len(grouped['examples']))
        self.assertEqual([],grouped['facts'])

    def test_unread_search_summary_can_be_confirmed_as_lead_without_fact_leakage(self):
        class Searcher:
            def search(self, owner, query, provider, targets):
                return {'results':[{'title':'A1摄影相机线索','url':'https://example.com/unread',
                    'snippet':'A1摄影相机搜索摘要；这段尚未读取正文。'}]}
        def reader(url):
            raise ValueError('source unavailable')
        jobs = ResearchJobs(self.store,searcher=Searcher(),reader=reader)
        job = jobs.create(self.owner,{'account_id':self.account,'queries':['A1摄影相机参考'],
            'provider':'bing','targets':['web'],'evidence_role':'expression_reference',
            'permission_confirmed':True,'confirmation_required':True,'key':'unread-search'})
        jobs.once()
        jobs.confirm(self.owner,job['id'],{'candidate_ids':[],'lead_urls':['https://example.com/unread'],
            'purpose':'expression_reference','key':'lead-confirmation'})
        doc = self.kb.get(self.owner,self.account,self.kb.list(self.owner,self.account)[0]['id'])
        self.assertEqual('https://example.com/unread',doc['source_url'])
        self.assertEqual('lead',doc['metadata']['research_case']['content_kind'])
        self.assertFalse(doc['metadata']['retrieval_eligible'])
        self.assertIn('A1摄影相机',doc['chunks'][0]['text'])
        grouped = self.kb.grouped_retrieve(self.owner,self.account,'A1摄影相机参考',self.target)
        self.assertEqual([],grouped['sources'])


if __name__ == '__main__':
    unittest.main()

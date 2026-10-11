"""Human approval is the ingestion boundary; synthetic network, real SQL storage.

The local-model PostgreSQL acceptance test explicitly uses the installed BGE
weights. It does not call paid models or claim that fixture search is real XHS.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from backend.contracts import DomainError
from backend.knowledge import Knowledge
from backend.live import messages_for
from backend.operations import Operations
from backend.provider import Config
from backend.research_jobs import ResearchJobs
from backend.service import Service
from backend.store import Store

MODEL = Path(__file__).resolve().parents[1]/'runtime/models/bge-small-zh-v1.5'


class PublicSearchFixture:
    calls = []
    def __init__(self, port): pass
    def identity(self): return {'id': 'a'*24}
    def search(self, query, filters=None):
        self.calls.append(('search', query))
        return {'feeds': [{'id': str(index)*24, 'xsecToken': 'fixture-search-token'} for index in (1, 2)]}
    def request(self, path, data):
        identity = data['feed_id'];self.calls.append(('read', identity))
        return {'note': {'noteId': identity, 'title': '白衬衫护理方法'+identity[0],
                'desc': '白衬衫采用纯棉面料，用冷水轻柔洗涤后自然晾干。先指出护理误区，再给出分步清单，末尾邀请读者讨论洗涤习惯。样本'+identity[0],
                'time': 1767225600000, 'interactInfo': {'likedCount': '321', 'collectedCount': '180'},
                'user': {'nickname': '公开案例作者'}}}


class ResearchConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_url = str(Path(self.temp.name)/'approval.sqlite')
        self.store = Store(self.db_url)
        self.prepare()

    def prepare(self):
        self.owner = 'approval-owner'
        self.service = Service(self.store, Config())
        self.account = Operations(self.store).read(self.owner)['accounts'][0]['id']
        self.kb = Knowledge(self.store, use_configured_embeddings=False)
        self.service.knowledge = self.kb
        self.jobs = ResearchJobs(self.store)
        with self.store.connect() as db:
            db.execute("INSERT INTO xhs_sync_links(owner,account_id,source_id,bridge_port,interval_s,enabled,status,next_at) VALUES(?,?,?,?,?,1,'ready',0)",
                       (self.owner, self.account, 'a'*24, 18061, 900))
        PublicSearchFixture.calls = []

    def tearDown(self): self.temp.cleanup()

    def packet(self, key='candidate-search'):
        return {'account_id': self.account, 'queries': ['白衬衫护理'], 'provider': 'xhs_local',
                'targets': ['xiaohongshu'], 'evidence_role': 'expression_reference',
                'permission_confirmed': True, 'confirmation_required': True, 'key': key,
                'style_filters': {'min_likes': 100, 'min_favorites': 50, 'sort_by': 'likes'}}

    def research(self):
        with patch('backend.xhs_research.LocalResearchClient', PublicSearchFixture):
            job = self.jobs.create(self.owner, self.packet())
            self.assertTrue(self.jobs.once())
        return self.jobs.get(self.owner, job['id'])

    def create_run(self, service=None):
        return (service or self.service).create(self.owner, {'topic': '白衬衫纯棉面料冷水护理',
                'audience': '需要护理白衬衫的读者', 'tone': '清楚', 'material': '白衬衫使用冷水洗涤。',
                'scenario': 'standard', 'allow_hypothesis': True, 'mode': 'simulation',
                'operations': {'account_id': self.account, 'platform': 'xiaohongshu', 'account': '我的账号'}})

    def approve(self, job, candidate=None, key='approve-one'):
        return self.jobs.confirm(self.owner, job['id'], {'candidate_ids': [candidate or job['candidates'][0]['id']], 'key': key})

    def test_canonical_queries_and_complete_scope_control_reuse(self):
        first=self.jobs.create(self.owner,{**self.packet('spaces'), 'queries':['  山地   徒步  ']})
        same=self.jobs.create(self.owner,{**self.packet('second'), 'queries':['山地 徒步']})
        self.assertEqual(first['queries'],['山地 徒步'])
        self.assertEqual(first['raw_queries'],['  山地   徒步  '])
        self.assertEqual(first['id'],same['id'])
        self.assertEqual(same['reuse']['kind'],'active_task')
        self.assertFalse(same['reuse']['cache_hit'])
        no_filter={**self.packet('no-filter'),'queries':['山地 徒步']};no_filter.pop('style_filters')
        different=self.jobs.create(self.owner,no_filter)
        self.assertNotEqual(first['id'],different['id'])

    def test_progress_survives_failure_and_records_actual_query(self):
        created=self.jobs.create(self.owner,self.packet('progress'))
        def fail(claim):
            self.jobs._progress(claim,{'phase':'search','query':'实际查询','attempt':1,'status':'failed',
                'error':'XHS_SEARCH_HTTP_500','error_origin':'mcp_http','mcp_http_status':500,'counts':{}})
            raise DomainError('XHS_SEARCH_HTTP_500','private response')
        with patch.object(self.jobs,'_execute',side_effect=fail):self.jobs.once()
        result=self.jobs.get(self.owner,created['id'])
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['trace'][0]['query'],'实际查询')
        self.assertEqual(result['error_origin'],'mcp_http')
        self.assertEqual(result['mcp_http_status'],500)
        self.assertEqual(result['outcome'],'search_failed')
        self.assertNotIn('private response',json.dumps(result))

    def test_absolute_task_deadline_cannot_be_extended_by_lease(self):
        import time
        created=self.jobs.create(self.owner,self.packet('deadline'));claim=self.jobs._claim()
        with self.store.connect() as db:
            p=json.loads(db.execute('SELECT payload FROM research_jobs WHERE id=?',(created['id'],)).fetchone()[0])
            p['deadline_at']=time.time()-1
            db.execute('UPDATE research_jobs SET payload=?,lease_until=? WHERE id=?',(json.dumps(p),time.time()+999,created['id']))
        result=self.jobs.get(self.owner,created['id'])
        self.assertEqual(result['status'],'failed');self.assertEqual(result['error'],'RESEARCH_TIMEOUT')
        with self.assertRaises(DomainError):self.jobs._change(claim)

    def test_outcomes_do_not_disguise_invalid_or_failed_records_as_empty(self):
        base={'attempts':[{'query':'x','status':'done','results':3}],'items':[],'candidates':[],'document_ids':[]}
        for counts,expected in [({'raw_count':0,'parsed_count':0},('done','empty_results')),
                ({'raw_count':3,'parsed_count':0},('failed','invalid_results')),
                ({'raw_count':3,'parsed_count':3,'detail_failed_count':3},('failed','detail_failed'))]:
            self.assertEqual(self.jobs._result({**base,'counts':counts}),expected)

    def test_research_collects_candidates_without_knowledge_or_model_context(self):
        job = self.research()
        self.assertEqual(job['status'], 'awaiting_confirmation')
        self.assertTrue(job['confirmation_required'])
        self.assertEqual(len(job['candidates']), 2)
        self.assertEqual(job['document_ids'], [])
        self.assertEqual(self.kb.list(self.owner, self.account), [])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM knowledge_documents').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM knowledge_chunks').fetchone()[0], 0)
        self.assertEqual(self.kb.retrieve(self.owner, self.account, '白衬衫护理', style_only=True)['sources'], [])
        result = self.create_run();run = self.store.get(result['run_id'], self.owner)
        self.assertEqual(run.context['evidence'], [])
        self.assertEqual(messages_for(run, 'research')[1]['retrieved_references'], [])
        self.assertIn('xsec_token=fixture-search-token', job['candidates'][0]['packet']['source_url'])

    def test_selected_approval_persists_once_and_rejects_unowned_or_unknown_candidates(self):
        job = self.research();chosen = job['candidates'][0]['id']
        with self.assertRaises(DomainError):
            self.jobs.confirm('other-owner', job['id'], {'candidate_ids': [chosen], 'key': 'wrong-owner'})
        with self.assertRaises(DomainError): self.approve(job, candidate='not-a-candidate', key='unknown')
        self.assertEqual(self.kb.list(self.owner, self.account), [])
        approved = self.approve(job);again = self.approve(job)
        self.assertEqual(approved['document_ids'], again['document_ids'])
        self.assertEqual(len(approved['document_ids']), 1)
        docs = self.kb.list(self.owner, self.account)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]['version'], 1)
        calls_before = list(PublicSearchFixture.calls)
        with self.assertRaises(DomainError) as changed:
            self.jobs.confirm(self.owner, job['id'], {'candidate_ids': [chosen], 'key': 'second-approval-key'})
        self.assertEqual(changed.exception.code, 'IDEMPOTENCY_CONFLICT')
        self.assertEqual(len(self.kb.list(self.owner, self.account)), 1)
        self.assertEqual(PublicSearchFixture.calls, calls_before)

    def test_platform_search_forces_confirmation_and_deduplicates_active_query(self):
        packet = self.packet();packet.pop('confirmation_required')
        with patch('backend.xhs_research.LocalResearchClient', PublicSearchFixture):
            first = self.jobs.create(self.owner, packet)
            packet['key'] = 'another-click'
            second = self.jobs.create(self.owner, packet)
            self.assertEqual(first['id'], second['id'])
            self.assertTrue(self.jobs.once())
        self.assertEqual(self.jobs.get(self.owner, first['id'])['status'], 'awaiting_confirmation')
        self.assertEqual(self.kb.list(self.owner, self.account), [])

    def test_successful_empty_search_is_not_a_connection_failure(self):
        with patch('backend.xhs_research.LocalResearchClient', PublicSearchFixture), patch.object(PublicSearchFixture,'search',return_value={'feeds':[]}):
            created=self.jobs.create(self.owner,self.packet());self.jobs.once()
        result=self.jobs.get(self.owner,created['id'])
        self.assertEqual(result['status'],'done')
        self.assertIsNone(result['error'])
        self.assertEqual(result['candidates'],[])
        self.assertEqual(self.kb.list(self.owner,self.account),[])

    def test_resigned_note_link_and_changed_body_reuse_existing_version(self):
        first = self.research();approved = self.approve(first)
        doc_id = approved['document_ids'][0]
        old = self.kb.get(self.owner, self.account, doc_id)
        packet = self.packet('search-again')
        with patch('backend.xhs_research.LocalResearchClient', PublicSearchFixture):
            created = self.jobs.create(self.owner, packet);self.jobs.once()
        second = self.jobs.get(self.owner, created['id'])
        with self.store.connect() as db:
            value = json.loads(db.execute('SELECT payload FROM research_jobs WHERE id=?', (created['id'],)).fetchone()[0])
            value['candidates'][0]['packet']['source_url'] += '&renewed=yes'
            value['candidates'][0]['packet']['text'] += '搜索中新采集到的变化不覆盖已有用户版本。'
            db.execute('UPDATE research_jobs SET payload=? WHERE id=?', (json.dumps(value), created['id']))
        result = self.approve(second, key='confirm-again')
        self.assertEqual(result['document_ids'], [doc_id])
        self.assertEqual(self.kb.get(self.owner, self.account, doc_id), old)
        self.assertEqual(len(self.kb.list(self.owner, self.account)), 1)

    def test_concurrent_confirmations_of_same_note_create_one_version(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        first=self.research()
        with patch('backend.xhs_research.LocalResearchClient', PublicSearchFixture):
            created=self.jobs.create(self.owner,self.packet('concurrent-search'));self.jobs.once()
        second=self.jobs.get(self.owner,created['id'])
        barrier=Barrier(2);save=self.jobs.cases.save
        def synchronized_save(*args,**kwargs):
            barrier.wait(timeout=15)
            return save(*args,**kwargs)
        with patch.object(self.jobs.cases,'save',side_effect=synchronized_save):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda job:self.approve(job,key='approve-'+job['id']),[first,second]))
        self.assertEqual(results[0]['document_ids'],results[1]['document_ids'])
        self.assertEqual(len(self.kb.list(self.owner,self.account)),1)
        self.assertEqual(self.kb.list(self.owner,self.account)[0]['version'],1)

    def test_only_link_candidate_cannot_be_imported(self):
        job = self.research()
        with self.store.connect() as db:
            value = json.loads(db.execute('SELECT payload FROM research_jobs WHERE id=?', (job['id'],)).fetchone()[0])
            value['candidates'][0]['packet']['text'] = ''
            value['candidates'][0]['importable'] = False
            db.execute('UPDATE research_jobs SET payload=? WHERE id=?', (json.dumps(value), job['id']))
        with self.assertRaises(DomainError) as caught:self.approve(job)
        self.assertEqual(caught.exception.code, 'CANDIDATE_UNREADABLE')
        self.assertEqual(self.kb.list(self.owner, self.account), [])

    def test_incremental_candidate_survives_later_transport_failure(self):
        def collect(research, owner, account, queries, check=None, on_note=None, **kwargs):
            research.expected_source_id = 'a'*24
            on_note({'account_id':account,'title':'已完成的公开笔记','text':'衬衣领子发黄时先确认面料和洗护标识，再根据说明处理。',
                     'source_url':'https://www.xiaohongshu.com/explore/first?xsec_token=fixture',
                     'platform':'xiaohongshu','content_kind':'text','evidence_role':'expression_reference',
                     'permission_confirmed':True,'observed_at':'2026-10-10T00:00:00+00:00',
                     'note_id':'first','content_type':'image'})
            raise DomainError('XHS_DETAIL_TIMEOUT','后续读取超时')
        with patch('backend.xhs_research.XHSResearch.collect', collect):
            job=self.jobs.create(self.owner,self.packet());self.jobs.once()
        result=self.jobs.get(self.owner,job['id'])
        self.assertEqual(result['error'],'XHS_DETAIL_TIMEOUT')
        self.assertEqual(len(result['candidates']),1)
        self.assertEqual(self.kb.list(self.owner,self.account),[])
        self.assertEqual(len(self.approve(result)['document_ids']),1)

    def test_confirmed_references_survive_restart_and_feed_four_role_messages(self):
        job = self.research();approved = self.approve(job)
        fresh_store = Store(self.db_url);fresh_service = Service(fresh_store, Config())
        fresh_service.knowledge = Knowledge(fresh_store, use_configured_embeddings=False)
        result = self.create_run(fresh_service);run = fresh_store.get(result['run_id'], self.owner)
        sources = run.context['style_retrieval']['sources']
        self.assertEqual({s['document_id'] for s in sources}, set(approved['document_ids']))
        expected = {s['source_id'] for s in sources};self.assertTrue(expected)
        # Reviewer messages require a draft, but this test never calls a model.
        run.drafts = [{'content': {'selected_title': '白衬衫护理', 'body': '按材料说明冷水洗涤。', 'cta': '你会怎样护理？', 'tags': []}}]
        for stage in ('audience', 'research', 'strategy', 'review'):
            instructions, payload = messages_for(run, stage)
            self.assertEqual({s['source_id'] for s in payload['retrieved_references']}, expected)
            self.assertTrue(all(s['version'] == 1 for s in payload['retrieved_references']))
            for phrase in ('标题', '开头', '结构', '节奏', 'CTA', 'source_id'):
                self.assertIn(phrase, instructions[0]['content'])


    def test_approved_ordinary_web_material_is_automatically_retrieved(self):
        class Search:
            def search(self, *args): return {'results': [{'url': 'https://example.com/shirt', 'title': '白衬衫护理说明'}]}
        def read(url):
            return {'url': url, 'title': '白衬衫护理说明', 'text': '白衬衫纯棉面料建议使用冷水护理，按洗涤、漂洗、自然晾干的结构说明方法。',
                    'fetched_at': '2026-10-10T00:00:00+00:00', 'verification': '已读取公开正文'}
        jobs = ResearchJobs(self.store, searcher=Search(), reader=read)
        packet = self.packet();packet.update(provider='bing', targets=['web']);packet.pop('style_filters')
        job = jobs.create(self.owner, packet);self.assertTrue(jobs.once())
        pending = jobs.get(self.owner, job['id'])
        self.assertEqual(pending['status'], 'awaiting_confirmation')
        self.assertEqual(self.kb.retrieve(self.owner, self.account, '白衬衫护理')['sources'], [])
        approved = jobs.confirm(self.owner, job['id'], {'candidate_ids': [pending['candidates'][0]['id']], 'key': 'approve-web'})
        run = self.create_run()
        self.assertEqual(run['context']['style_retrieval']['sources'], [])
        self.assertEqual({s['document_id'] for s in run['context']['approved_retrieval']['sources']}, set(approved['document_ids']))
        self.assertEqual({s['document_id'] for s in run['context']['evidence']}, set(approved['document_ids']))
        doc = self.kb.get(self.owner, self.account, approved['document_ids'][0])
        self.assertTrue(doc['metadata']['research_case']['provenance']['human_confirmed'])

    def test_cancellation_between_selection_and_save_blocks_late_ingestion(self):
        job = self.research();original_save = self.jobs.cases.save
        def cancelled_save(*args, **kwargs):
            self.jobs.cancel(self.owner, job['id'])
            return original_save(*args, **kwargs)
        with patch.object(self.jobs.cases, 'save', side_effect=cancelled_save):
            with self.assertRaises(DomainError) as caught: self.approve(job)
        self.assertEqual(caught.exception.code, 'RESEARCH_STOPPED')
        self.assertEqual(self.jobs.get(self.owner, job['id'])['status'], 'cancelled')
        self.assertEqual(self.kb.list(self.owner, self.account), [])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM knowledge_versions').fetchone()[0], 0)

    def test_cancel_after_first_import_can_resume_same_selection_without_overwriting(self):
        job=self.research()
        data={'candidate_ids':[c['id'] for c in job['candidates']], 'key':'resume-selection'}
        save=self.jobs.cases.save;calls=[]
        def cancel_second(*args,**kwargs):
            calls.append(True)
            if len(calls)==2:self.jobs.cancel(self.owner,job['id'])
            return save(*args,**kwargs)
        with patch.object(self.jobs.cases,'save',side_effect=cancel_second):
            with self.assertRaises(DomainError) as stopped:self.jobs.confirm(self.owner,job['id'],data)
        self.assertEqual(stopped.exception.code,'RESEARCH_STOPPED')
        self.assertEqual(self.jobs.get(self.owner,job['id'])['status'],'cancelled')
        self.assertEqual(len(self.kb.list(self.owner,self.account)),1)
        existing=self.kb.list(self.owner,self.account)[0]
        resumed=self.jobs.confirm(self.owner,job['id'],data)
        self.assertEqual(resumed['status'],'done')
        self.assertEqual(len(resumed['document_ids']),2)
        self.assertEqual(len(self.kb.list(self.owner,self.account)),2)
        self.assertEqual(self.kb.get(self.owner,self.account,existing['id'])['version'],1)
        again=self.jobs.confirm(self.owner,job['id'],data)
        self.assertEqual(again['document_ids'],resumed['document_ids'])

    def test_abbreviated_metric_display_stays_separate_from_numeric_metrics(self):
        from backend.research_jobs import ResearchJobs
        created=self.jobs.create(self.owner,self.packet('display-metrics'))
        job=self.jobs._claim()
        self.jobs._stage(job, {'account_id':self.account,'title':'带原始互动的公开笔记',
            'text':'衬衣领子发黄后需要先核对面料和洗护标识，避免误用洗护用品。',
            'source_url':'https://www.xiaohongshu.com/explore/display-id?xsec_token=fixture',
            'platform':'xiaohongshu','content_kind':'text','evidence_role':'expression_reference',
            'permission_confirmed':True,'observed_at':'2026-10-10T00:00:00+00:00',
            'metrics':{'likes':None},'metric_display':{'likes':'1.2万'},'note_id':'display-id'},
            'local_browser_public_note',{'binding_source_id':'a'*24},'2026-10-10T00:00:00+00:00')
        self.jobs._await_confirmation(job)
        pending=self.jobs.get(self.owner,created['id'])
        candidate=pending['candidates'][0]
        self.assertEqual(candidate['preview']['metric_display']['likes'],'1.2万')
        self.assertNotIn('metric_display',candidate['packet'])
        approved=self.approve(pending)
        doc=self.kb.get(self.owner,self.account,approved['document_ids'][0])
        self.assertIsNone(doc['metadata']['research_case']['metrics']['likes'])
        self.assertEqual(doc['metadata']['research_case']['provenance']['metric_display']['likes'],'1.2万')

    def test_binding_change_between_selection_and_save_blocks_late_ingestion(self):
        job = self.research();original_save = self.jobs.cases.save
        def rebound_save(*args, **kwargs):
            with self.store.connect() as db:
                db.execute('UPDATE xhs_sync_links SET source_id=? WHERE owner=? AND account_id=?', ('b'*24, self.owner, self.account))
            return original_save(*args, **kwargs)
        with patch.object(self.jobs.cases, 'save', side_effect=rebound_save):
            with self.assertRaises(DomainError) as caught: self.approve(job)
        self.assertEqual(caught.exception.code, 'XHS_IDENTITY_CHANGED')
        self.assertEqual(self.kb.list(self.owner, self.account), [])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM knowledge_chunks').fetchone()[0], 0)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'PostgreSQL integration requires TEST_DATABASE_URL')
class PostgresResearchConfirmationTests(ResearchConfirmationTests):
    def setUp(self):
        import psycopg
        self.temp = tempfile.TemporaryDirectory()
        self.schema = 'youji_test_confirm_'+uuid4().hex
        self.base = os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base, autocommit=True) as db: db.execute('CREATE SCHEMA '+self.schema)
        self.db_url = self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema
        self.store = Store(self.db_url)
        self.prepare()

    def tearDown(self):
        import psycopg
        with psycopg.connect(self.base, autocommit=True) as db: db.execute('DROP SCHEMA '+self.schema+' CASCADE')
        self.temp.cleanup()

    @unittest.skipUnless((MODEL/'youji-model-manifest.json').is_file(), 'Install optional pinned local model first')
    def test_approved_pg_content_uses_real_bge_vectors_after_service_restart(self):
        from backend.embeddings import LocalEmbeddings
        job = self.research();approved = self.approve(job)
        fresh_store = Store(self.db_url)
        kb = Knowledge(fresh_store, embedding_provider=LocalEmbeddings(str(MODEL)))
        result = kb.retrieve(self.owner, self.account, '白衬衫纯棉面料冷水护理', style_only=True)
        self.assertEqual(result['engine'], 'hybrid-bm25-local-rrf-v1')
        self.assertEqual({s['document_id'] for s in result['sources']}, set(approved['document_ids']))
        self.assertTrue(any(s.get('semantic_rank') is not None for s in result['sources']))
        self.assertTrue(all(s['semantic_score'] > 0.4 for s in result['sources']))
        service = Service(fresh_store, Config());service.knowledge = kb
        created = self.create_run(service)
        self.assertEqual(created['context']['style_retrieval']['engine'], 'hybrid-bm25-local-rrf-v1')
        self.assertEqual({s['source_id'] for s in created['context']['evidence']}, {s['source_id'] for s in result['sources']})

"""Reference links are read before search leads, with unchanged evidence guards."""
import tempfile
import json
from dataclasses import asdict
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from backend.contracts import DomainError
from backend.provider import Config
from backend.service import Service
from backend.store import Store
from backend.worker import Worker
from backend.web_research import collect, reference_urls, attach_facts
from test_live_provider import FixtureModel


QUERY='家电 QX7 Pro 产品规格'
URL='https://example.com/products/'


def article(url):
    return {'url':url,'title':'QX 7 Pro 产品规格','text':'QX 7 Pro 产品规格与使用条件，以本页说明为准。'*10,
            'verification':'fixture only','fetched_at':'2026-11-04T00:00:00Z','published_at':None}


def empty_search(query):
    return {'provider':'fixture only','results':[]}


class ReferenceLinkTests(unittest.TestCase):
    def test_extract_bounded_links_without_trailing_prose_punctuation(self):
        text='来源：https://example.com/products/。\n(https://example.com/specs)\n'+URL+'\nhttps://example.com/third\nhttps://example.com/fourth'
        self.assertEqual(reference_urls(text),[URL,'https://example.com/specs','https://example.com/third'])

    def test_author_reference_precedes_search_and_duplicate_lead_is_not_read_again(self):
        order=[]
        def read(url):order.append(('read',url));return article(url)
        def search(query):
            order.append(('search',query))
            return {'provider':'fixture','results':[{'url':URL,'title':'QX 7 Pro'}]}
        with patch('backend.sources.read_article',side_effect=read):
            report=collect([QUERY],source_urls=[URL,URL],searcher=search)
        self.assertEqual(order,[('read',URL),('search',QUERY)])
        self.assertEqual(report['status'],'complete')
        self.assertEqual(report['sources'][0]['candidate_origin'],'user_reference')
        self.assertTrue(report['sources'][0]['body_read'])

    def test_successful_reference_survives_search_failure_and_attach_facts(self):
        with patch('backend.sources.read_article',side_effect=article):
            report=collect([QUERY],source_urls=[URL],searcher=lambda q:(_ for _ in ()).throw(DomainError('SOURCE_UNAVAILABLE','search unavailable')))
        self.assertEqual(report['search_status'],'failed')
        self.assertEqual(report['status'],'complete')
        context={'topic':QUERY,'creation_classification':{'domains':['general']},
                 'creation_retrieval':{'groups':{'facts':[],'methods':[],'examples':[]}}}
        attach_facts(context,report)
        self.assertEqual(context['creation_retrieval']['web_fact_filter']['accepted'],1)
        self.assertEqual(context['creation_retrieval']['groups']['facts'][0]['url'],URL)
        self.assertEqual(report['status'],'complete')

    def test_reference_failures_share_the_eight_read_budget(self):
        urls=[f'https://example.com/ref{i}' for i in range(4)]
        rows=[{'url':f'https://example.com/result{i}','title':'QX 7 Pro'} for i in range(8)]
        with patch('backend.sources.read_article',side_effect=DomainError('SOURCE_HTTP_403','HTTP 403')) as read:
            report=collect([QUERY],source_urls=urls,searcher=lambda q:{'provider':'fixture','results':rows})
        self.assertEqual(read.call_count,1)
        self.assertEqual(report['read_requests'],1)
        self.assertEqual(len(report['reads']),11)
        self.assertEqual([r['url'] for r in report['reads'][:3]],urls[:3])
        self.assertNotIn(urls[3],[r['url'] for r in report['reads']])
        self.assertEqual(report['status'],'insufficient')
        self.assertTrue(all(not row['body_read'] for row in report['reads']))

    def test_reference_origin_does_not_bypass_topic_or_url_safety(self):
        with patch('backend.sources.read_article',return_value={**article(URL),'title':'R9','text':'R9 另外一种产品，没有所需型号信息。'*10}):
            report=collect([QUERY],source_urls=[URL],searcher=empty_search)
        self.assertEqual(report['sources'],[])
        self.assertIn('主题或型号不匹配',report['reads'][0]['error'])
        with patch('backend.sources.fetch_public') as fetch:
            report=collect([QUERY],source_urls=['http://localhost/private'],searcher=empty_search)
        fetch.assert_not_called()
        self.assertEqual(report['sources'],[])
        self.assertIn('本机或内网',report['reads'][0]['error'])

    def test_cancellation_before_reference_read_propagates(self):
        def cancelled():raise DomainError('JOB_PAUSED','cancelled')
        with patch('backend.sources.read_article') as read:
            with self.assertRaises(DomainError):collect([QUERY],source_urls=[URL],before_request=cancelled)
        read.assert_not_called()

    def test_reference_only_never_invokes_search_even_if_read_fails(self):
        with patch('backend.sources.read_article',side_effect=DomainError('SOURCE_HTTP_403','denied')),patch('backend.sources.search_web') as search:
            report=collect([QUERY],source_urls=[URL],references_only=True)
        search.assert_not_called()
        self.assertEqual(report['status'],'insufficient')
        self.assertTrue(report['references_only'])
        self.assertEqual(report['searches'],[])


class ReferenceRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'test.sqlite')
        self.model=FixtureModel()
        self.service=Service(self.store,Config('fixture'),self.model)
        self.owner='reference-test'
        self.run_id=self.service.create(self.owner,dict(topic='公共资料测试',audience='读者',tone='清楚',
            material='公开资料测试正文。来源：'+URL,allow_hypothesis=True,mode='live',
            web_research={'enabled':True,'queries':['公开资料测试']}))['run_id']

    def tearDown(self):self.tmp.cleanup()

    def step(self,action='step'):
        run=self.store.get(self.run_id,self.owner)
        self.service.background(self.owner,self.run_id,dict(action=action,version=run.status_version,key=str(uuid4()),
            **({'queries':['公开资料测试']} if action=='retry_research' else {})))

    def read(self,url):
        return {**article(url),'title':'公开资料测试','text':'公开资料测试原始正文及适用条件。'*20}

    def test_reference_only_retry_preserves_paid_provider_without_charging_search(self):
        with patch('backend.sources.read_article',side_effect=self.read),patch('backend.sources.search_web',side_effect=empty_search):
            self.step();Worker(self.service).once()
        run=self.store.get(self.run_id,self.owner)
        run.context['web_research']['provider']='baidu'
        with self.store.connect() as db:
            db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(asdict(run)),self.run_id))
        self.service.background(self.owner,self.run_id,dict(action='retry_research',version=run.status_version,key=str(uuid4()),queries=['公开资料测试'],references_only=True))
        with patch('backend.sources.read_article',side_effect=self.read),patch('backend.search_providers.SearchSettings.search') as paid,patch('backend.sources.search_web') as free:
            Worker(self.service).once()
        paid.assert_not_called();free.assert_not_called()
        after=self.store.get(self.run_id,self.owner)
        self.assertEqual(after.context['web_research']['status'],'complete')
        self.assertEqual(after.context['web_research']['provider'],'baidu')
        self.assertEqual(self.model.calls,[])

    def test_runtime_refreshes_pristine_completed_research_and_still_stops_before_models(self):
        with patch('backend.sources.read_article',side_effect=self.read) as read,patch('backend.sources.search_web',side_effect=empty_search):
            self.step();Worker(self.service).once()
            first=self.store.get(self.run_id,self.owner)
            self.assertEqual(first.context['web_research']['sources'][0]['candidate_origin'],'user_reference')
            self.assertEqual(self.model.calls,[])
            self.step('retry_research');Worker(self.service).once()
        after=self.store.get(self.run_id,self.owner)
        self.assertEqual(read.call_count,2)
        self.assertEqual(after.context['web_research_history'][0]['status'],'complete')
        self.assertNotEqual(after.snapshot_id,first.snapshot_id)
        self.assertEqual(self.model.calls,[])
        self.assertEqual(self.service.jobs.public(self.run_id,self.owner)['status'],'paused')
        # Once analysis has started, even a linked task cannot replace evidence.
        self.step();Worker(self.service).once()
        with self.assertRaises(DomainError):self.step('retry_research')

    def test_regeneration_history_cannot_hide_a_failed_model_attempt(self):
        with patch('backend.sources.read_article',side_effect=self.read),patch('backend.sources.search_web',side_effect=empty_search):
            self.step();Worker(self.service).once()
        run=self.store.get(self.run_id,self.owner)
        run.context['research_regenerations']=[{'id':'historical-regeneration'}]
        with self.store.connect() as db:
            db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(asdict(run)),self.run_id))
        with patch.object(self.model,'complete',side_effect=DomainError('PROVIDER_ERROR','fixture failure')):
            self.step();Worker(self.service).once()
        run=self.store.get(self.run_id,self.owner)
        self.assertEqual(run.current_stage,'brief')
        self.assertFalse(run.artifacts)
        self.assertFalse(run.node_runs)
        with self.store.connect() as db:
            self.assertIsNotNone(db.execute('SELECT 1 FROM live_calls WHERE run_id=?',(self.run_id,)).fetchone())
        with self.assertRaises(DomainError):self.step('retry_research')

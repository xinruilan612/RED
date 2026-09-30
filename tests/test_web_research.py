import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from backend.contracts import DomainError
from backend.provider import Config
from backend.service import Service
from backend.store import Store
from backend.worker import Worker
from backend.web_research import collect, selection
from test_live_provider import FixtureModel


def found(query):
    return {'provider':'fixture only','results':[{'title':'公开资料测试','url':f'https://example.com/{query}/{i}','snippet':'unread snippet','body_read':False} for i in range(4)]}


def article(url):
    return {'title':'公开资料测试','url':url,'text':'公开资料测试正文，提供清楚的来源，但并不是平台热榜。'*30,
            'fetched_at':'2026-09-30T00:00:00+00:00','published_at':None,'verification':'fixture only'}


class WebResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'test.sqlite');self.prepare()

    def prepare(self):
        self.model=FixtureModel();self.service=Service(self.store,Config('fixture'),self.model);self.owner='web-test'
        self.run_id=self.service.create(self.owner,dict(topic='公共资料测试',audience='读者',tone='朴实',material='这是一份公开资料的测试摘要。',allow_hypothesis=True,mode='live',web_research={'enabled':True,'queries':['公开资料测试']}))['run_id']

    def tearDown(self):self.tmp.cleanup()
    def run_value(self):return self.store.get(self.run_id,self.owner)
    def start(self):self.service.background(self.owner,self.run_id,{'action':'start','version':self.run_value().status_version,'key':str(uuid4())})

    def test_explicit_selection_and_bounds(self):
        self.assertFalse(selection(None,'simulation')['enabled'])
        for value,mode in [({'enabled':True,'queries':['a']},'live'),({'enabled':True,'queries':['abc']*3},'live'),({'enabled':True,'queries':['abc']},'simulation')]:
            with self.assertRaises(DomainError):selection(value,mode)

    def test_tool_limits_and_excerpts(self):
        with patch('backend.sources.search_web',side_effect=found) as search,patch('backend.sources.read_article',side_effect=article) as read:
            result=collect(['公开资料测试','资料测试'])
        self.assertEqual(search.call_count,2);self.assertEqual(read.call_count,3)
        self.assertEqual(result['model_calls'],0);self.assertEqual(len(result['sources']),3)
        self.assertTrue(all(len(s['text'])<=400 and s['heat'] is None and s['published_at'] is None for s in result['sources']))

    def test_worker_shared_evidence_and_replay_no_extra_search(self):
        self.start()
        with patch('backend.sources.search_web',side_effect=found) as search,patch('backend.sources.read_article',side_effect=article):
            Worker(self.service).once()
            self.assertEqual(search.call_count,1)
        run=self.run_value();self.assertEqual(run.wait_reason,'final_confirmation',self.service.jobs.public(self.run_id,self.owner))
        self.assertEqual(len(self.model.calls),8)
        for node in run.node_runs:
            self.assertTrue(any(s['source_id'].startswith('web:') for s in node['input']['materials']))
            self.assertNotIn('unread snippet',str(node['input']))
        self.assertEqual(run.context['web_research']['status'],'complete')

    def test_empty_results_block_models_and_never_auto_retry(self):
        self.start()
        with patch('backend.sources.search_web',return_value={'provider':'fixture','results':[]}) as search:
            Worker(self.service).once();self.start();Worker(self.service).once()
            self.assertEqual(search.call_count,1)
        self.assertEqual(self.model.calls,[]);self.assertEqual(self.run_value().context['web_research']['status'],'insufficient')

    def test_interrupted_search_is_not_reissued(self):
        self.start()
        def crash(point,stage):
            if point=='after_web_response':raise RuntimeError('crash')
        with patch('backend.sources.search_web',side_effect=found) as search,patch('backend.sources.read_article',side_effect=article):
            Worker(self.service,fault=crash).once();self.start();Worker(self.service).once()
            self.assertEqual(search.call_count,1)
        self.assertEqual(self.model.calls,[])

    def test_cancel_rejects_late_web_evidence(self):
        self.start()
        def cancel(query):
            run=self.run_value();self.service.action(self.owner,self.run_id,{'action':'cancel','version':run.status_version,'key':str(uuid4()),'payload':{}})
            return found(query)
        with patch('backend.sources.search_web',side_effect=cancel),patch('backend.sources.read_article') as read:
            Worker(self.service).once();read.assert_not_called()
        self.assertEqual(self.run_value().run_status,'CANCELLED');self.assertEqual(self.model.calls,[])


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'requires PostgreSQL')
class PostgresWebResearchTests(WebResearchTests):
    def setUp(self):
        import psycopg
        self.tmp=tempfile.TemporaryDirectory();self.base=os.environ['TEST_DATABASE_URL'];self.schema='youji_test_'+uuid4().hex
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('CREATE SCHEMA '+self.schema)
        self.store=Store(self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema);self.prepare()

    def tearDown(self):
        import psycopg
        super().tearDown()
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('DROP SCHEMA '+self.schema+' CASCADE')

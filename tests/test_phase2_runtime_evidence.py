"""Real SQL/runtime acceptance with synthetic search and an unpaid model adapter.

No result here proves real XHS collection or model writing quality. PostgreSQL
cases require TEST_DATABASE_URL and create/drop only an isolated test schema.
"""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from backend.contracts import DomainError
from backend.knowledge import Knowledge
from backend.live import schema
from backend.provider import Config
from backend.service import Service
from backend.store import Store
from backend.worker import Worker
import test_research_confirmation as confirmation
from test_original_creation_http import RoutingVectors


class EvidenceModel:
    def __init__(self): self.calls = []

    def complete(self, messages):
        stage = re.search(r'负责 (\w+) 的', messages[0]['content']).group(1)
        payload = json.loads(messages[1]['content'])
        self.calls.append((stage, payload))
        result = schema(stage)
        source = payload['materials'][0]
        reference = (payload['retrieved_references'] or [source])[0]
        source_id = source['source_id']
        attribution = reference['source_id'] + '：借鉴问题到清单的结构，不移植产品事实。'
        if stage == 'audience': result['basis'] = attribution
        if stage == 'research':
            result['facts'] = [{'source_id': source_id, 'quote': source['text']}]
            result['prohibited_claims'] = [attribution]
        if stage == 'strategy': result['why_account'] = attribution
        if stage == 'body':
            result['selected_title'] = '候选一'
            result['body'] = source['text']
        if stage == 'review':
            result['limitations'] = [attribution]
            result['checks'][-2]['result'] = 'unknown'
            result['claim_map'] = [{'excerpt': source['text'], 'source_id': source_id, 'quote': source['text']}]
        return result, 120


class RuntimeEvidenceTests(unittest.TestCase):
    prepare = confirmation.ResearchConfirmationTests.prepare
    packet = confirmation.ResearchConfirmationTests.packet
    research = confirmation.ResearchConfirmationTests.research
    approve = confirmation.ResearchConfirmationTests.approve

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_url = str(Path(self.temp.name)/'runtime-evidence.sqlite')
        self.store = Store(self.db_url)
        self.prepare()
        self.configure()

    def configure(self):
        self.model = EvidenceModel()
        self.config = Config('fixture-key-never-sent')
        self.service = Service(self.store, self.config, self.model)
        self.kb.embedding_provider=RoutingVectors()
        self.service.knowledge = self.kb
        self.approved = self.approve(self.research())
        for identity in self.approved['document_ids']:
            doc=self.kb.get(self.owner,self.account,identity)
            self.kb.save(self.owner,dict(account_id=self.account,title=doc['title'],text=doc['chunks'][0]['text'],document_id=identity,expected_version=doc['version'],classification=dict(domains=['apparel'],channel='xiaohongshu',format='note',material_type='example')),source_type='research_case',source_url=doc['source_url'],metadata=doc['metadata'])
        self.run_id = self.service.create(self.owner, {
            'creation': {'domains':['apparel'],'channel':'xiaohongshu','format':'note'},
            'topic': '白衬衫纯棉面料冷水护理', 'audience': '白衬衫读者', 'tone': '清楚',
            'material': '用户产品仅确认纯棉面料。', 'allow_hypothesis': True,
            'mode': 'live', 'web_research': {'enabled': False, 'queries': []},
            'operations': {'account_id': self.account, 'platform': 'xiaohongshu', 'account': '虚构账号'}
        })['run_id']

    def tearDown(self): self.temp.cleanup()
    def run_value(self): return self.store.get(self.run_id, self.owner)

    def start(self, service=None):
        service = service or self.service
        return service.background(self.owner, self.run_id, {
            'action': 'start', 'version': self.run_value().status_version, 'key': str(uuid4())})

    def test_confirmed_source_reaches_every_actual_model_call_and_review_trace(self):
        with patch('backend.web_research.collect', side_effect=AssertionError('network disabled')) as collect:
            self.start(); Worker(self.service).once()
        collect.assert_not_called()
        run = self.run_value()
        self.assertEqual(run.wait_reason, 'final_confirmation', self.service.jobs.public(self.run_id, self.owner))
        self.assertEqual(len(self.model.calls), 8)
        expected = {s['source_id'] for s in run.context['evidence']}
        for stage, payload in self.model.calls:
            with self.subTest(stage=stage):
                self.assertEqual({s['source_id'] for s in payload['retrieved_references']}, expected)
                self.assertTrue(all(s['version'] == 2 and s['url'] and s['case_ref']['observed_at'] for s in payload['retrieved_references']))
                self.assertNotIn('web_research', payload)
        self.assertEqual(run.review['claim_map'][0]['source_id'], 'user-material')
        calls = self.service.executor.public(run)['calls']
        self.assertEqual(len(calls), 8)
        for call in calls:
            self.assertEqual(call['snapshot_id'], run.snapshot_id)
            self.assertTrue(any(s.get('source_id') in expected for s in call['sources']))
        self.assertEqual(run.run_status, 'WAITING_USER')

    def test_restart_after_received_response_preserves_frozen_evidence_without_recall(self):
        initial = self.run_value().context['evidence']
        self.start(); tripped = []
        def fault(point, stage):
            if point == 'after_response' and stage == 'outline' and not tripped:
                tripped.append(True); raise RuntimeError('fixture interruption after saved response')
        Worker(self.service, fault=fault).once()
        self.assertEqual(self.service.jobs.public(self.run_id, self.owner)['status'], 'blocked')
        # Disable the library document after snapshot creation; audit evidence remains.
        doc = self.kb.list(self.owner, self.account)[0]
        self.kb.delete(self.owner, self.account, doc['id'], doc['version'])
        fresh = Service(Store(self.db_url), self.config, self.model)
        fresh.knowledge = Knowledge(fresh.store, use_configured_embeddings=False)
        self.start(fresh); Worker(fresh).once()
        self.assertEqual(self.run_value().wait_reason, 'final_confirmation')
        self.assertEqual(self.run_value().context['evidence'], initial)
        self.assertEqual([stage for stage, _ in self.model.calls].count('outline'), 1)
        self.assertEqual(len(self.model.calls), 8)
        self.assertEqual(len([a for a in self.run_value().artifacts if a['stage'] == 'outline']), 1)

    def test_selected_private_material_excludes_automatic_references_and_network(self):
        selected = self.kb.save(self.owner, {
            'account_id': self.account, 'title': '授权产品资料',
            'classification':dict(domains=['apparel'],channel='any',format='any',material_type='fact'),
            'text': '白衬衫纯棉面料护理问题：产品洗标建议冷水轻柔洗涤，避免高温烘干。'})
        self.service.action(self.owner, self.run_id, {
            'action': 'cancel', 'version': self.run_value().status_version,
            'key': 'cancel-for-explicit-selection', 'payload': {}})
        packet = {
            'creation': {'domains':['apparel'],'channel':'xiaohongshu','format':'note'},
            'topic': '白衬衫纯棉面料冷水护理', 'audience': '白衬衫读者', 'tone': '清楚',
            'material': '', 'allow_hypothesis': True, 'mode': 'live',
            'web_research': {'enabled': False, 'queries': []},
            'knowledge': {'enabled': True, 'document_ids': [selected['id']], 'automatic_references': False},
            'operations': {'account_id': self.account, 'platform': 'xiaohongshu', 'account': '虚构账号'}}
        for invalid in ('false', 0, None):
            with self.subTest(invalid=invalid), self.assertRaises(DomainError) as error:
                self.service.create(self.owner, {**packet, 'knowledge': {**packet['knowledge'], 'automatic_references': invalid}})
            self.assertEqual(error.exception.code, 'INVALID_INPUT')
        with patch('backend.web_research.collect', side_effect=AssertionError('network disabled')) as collect:
            created = self.service.create(self.owner, packet)
            self.run_id = created['run_id']
            self.assertEqual(created['context']['knowledge_selection'], packet['knowledge'])
            self.assertEqual({s['document_id'] for s in created['context']['evidence']}, {selected['id']})
            self.assertNotIn('style_retrieval', created['context'])
            self.assertNotIn('approved_retrieval', created['context'])
            self.start(); Worker(self.service).once()
        collect.assert_not_called()
        self.assertEqual(self.run_value().wait_reason, 'final_confirmation')
        self.assertEqual(len(self.model.calls), 8)
        for stage, payload in self.model.calls:
            with self.subTest(stage=stage):
                self.assertEqual(payload['retrieved_references'], [])
                self.assertEqual({s['document_id'] for s in payload['materials']}, {selected['id']})
                self.assertTrue(all(s['text'] == selected['chunks'][0]['text'] for s in payload['materials']))
                self.assertNotIn('web_research', payload)
        self.assertTrue(set(self.approved['document_ids']).isdisjoint({s['document_id'] for s in self.run_value().context['evidence']}))

    def test_runtime_adapter_keeps_source_location_and_original_hash(self):
        from backend.live import run_evidence
        source = {'source_id': 'kb:location', 'text': '授权原文', 'offset': 23,
                  'body_hash': 'stored-original-hash', 'version': 2, 'url': 'https://example.com/source'}
        copied = run_evidence({'evidence': [source]})[0]
        self.assertEqual(copied, source)

    def test_same_owner_other_account_has_no_confirmed_sources(self):
        from backend.accounts import PROFILE_FIELDS
        ops = self.service.operations
        state = ops.command(self.owner, {
            'action': 'save_account', 'version': ops.read(self.owner)['version'], 'key': str(uuid4()),
            'payload': {'id': '', 'name': '第二个独立账号', 'platform': 'xiaohongshu',
                        'profile': {**{key: '' for key in PROFILE_FIELDS}, 'weekly_frequency': 3}}})
        other = state['accounts'][-1]['id']
        self.assertNotEqual(other, self.account)
        self.assertEqual(self.kb.retrieve(self.owner, other, '白衬衫', style_only=True)['sources'], [])
        with self.assertRaises(DomainError):
            self.kb.get(self.owner, other, self.approved['document_ids'][0])
        self.service.action(self.owner, self.run_id, {'action': 'cancel', 'version': self.run_value().status_version, 'key': 'cancel-before-account-change', 'payload': {}})
        created = self.service.create(self.owner, {
            'creation': {'domains':['apparel'],'channel':'xiaohongshu','format':'note'},
            'topic': '白衬衫纯棉面料冷水护理', 'audience': '读者', 'tone': '清楚',
            'material': '独立账号资料', 'allow_hypothesis': True, 'mode': 'live',
            'operations': {'account_id': other, 'platform': 'xiaohongshu', 'account': '第二个独立账号'}})
        self.assertEqual(created['context']['evidence'], [])
        self.assertEqual(self.model.calls, [])

    def test_http_login_confirm_run_background_and_get_preserve_sources(self):
        from backend.api import create_app
        from fastapi.testclient import TestClient
        from backend.research_jobs import ResearchJobs
        model = EvidenceModel()
        with patch('backend.api.settings', return_value={}):
            app = create_app(self.store, self.config, origin='http://testserver', invite='', client=model)
        app.state.service.knowledge = Knowledge(self.store, embedding_provider=RoutingVectors())
        with TestClient(app) as client:
            csrf = client.get('/api/session').json()['csrf']
            def post(url, data):
                return client.post(url, json=data, headers={'Origin': 'http://testserver', 'X-CSRF-Token': csrf})
            credentials = {'username': 'phase2_http', 'password': 'Test-long-password'}
            response = post('/api/auth/register', credentials)
            self.assertEqual(response.status_code, 200, response.text)
            csrf = response.json()['csrf']
            self.assertEqual(post('/api/auth/logout', {}).status_code, 200)
            csrf = client.get('/api/session').json()['csrf']
            response = post('/api/auth/login', credentials)
            self.assertEqual(response.status_code, 200, response.text)
            csrf = response.json()['csrf']
            owner = app.state.auth.session(client.cookies.get('youji_session'))['owner']
            account = client.get('/api/operations').json()['accounts'][0]['id']
            with self.store.connect() as db:
                db.execute("INSERT INTO xhs_sync_links(owner,account_id,source_id,bridge_port,interval_s,enabled,status,next_at) VALUES(?,?,?,?,?,1,'ready',0)",
                           (owner, account, 'b'*24, 18062, 900))
            packet = self.packet('http-search'); packet['account_id'] = account
            class HTTPSource(confirmation.PublicSearchFixture):
                def identity(self): return {'id': 'b'*24}
            with patch('backend.xhs_research.LocalResearchClient', HTTPSource):
                response = post('/api/research/jobs', packet)
                self.assertEqual(response.status_code, 202, response.text)
                job_id = response.json()['id']
                self.assertTrue(ResearchJobs(self.store).once())
            job = client.get('/api/research/jobs/'+job_id).json()
            self.assertEqual(job['status'], 'awaiting_confirmation')
            response = post('/api/research/jobs/'+job_id+'/confirm', {
                'candidate_ids': [job['candidates'][0]['id']], 'key': 'http-confirm'})
            self.assertEqual(response.status_code, 200, response.text)
            document_ids = set(response.json()['document_ids'])
            for doc_id in document_ids:
                kb=app.state.service.knowledge;doc=kb.get(owner,account,doc_id)
                kb.save(owner,dict(account_id=account,title=doc['title'],text=doc['chunks'][0]['text'],document_id=doc_id,expected_version=doc['version'],classification=dict(domains=['apparel'],channel='xiaohongshu',format='note',material_type='example')),source_type='research_case',source_url=doc['source_url'],metadata=doc['metadata'])
            with patch('backend.web_research.collect', side_effect=AssertionError('network disabled')) as collect:
                response = post('/api/runs', {
                    'creation': {'domains':['apparel'],'channel':'xiaohongshu','format':'note'},
            'topic': '白衬衫纯棉面料冷水护理', 'audience': '白衬衫读者', 'tone': '清楚',
                    'material': '用户产品仅确认纯棉面料。', 'allow_hypothesis': True,
                    'mode': 'live', 'web_research': {'enabled': False, 'queries': []},
                    'operations': {'account_id': account, 'platform': 'xiaohongshu', 'account': 'HTTP测试账号'}})
                self.assertEqual(response.status_code, 201, response.text)
                created = response.json(); identity = created['run_id']
                response = post('/api/runs/'+identity+'/background', {
                    'action': 'start', 'version': created['status_version'], 'key': 'http-start'})
                self.assertEqual(response.status_code, 202, response.text)
                Worker(app.state.service).once()
            collect.assert_not_called()
            response = client.get('/api/runs/'+identity)
            self.assertEqual(response.status_code, 200, response.text)
            run = response.json()
            self.assertEqual(run['wait_reason'], 'final_confirmation', run)
            sources = run['context']['evidence']
            self.assertEqual({source['document_id'] for source in sources}, document_ids)
            self.assertEqual(len(model.calls), 8)
            expected = {source['source_id'] for source in sources}
            self.assertEqual(run['review']['claim_map'][0]['source_id'], 'user-material')
            for _, payload in model.calls:
                self.assertEqual({source['source_id'] for source in payload['retrieved_references']}, expected)

    def test_other_owner_cannot_read_start_or_retrieve_evidence(self):
        with self.assertRaises(DomainError): self.store.get(self.run_id, 'other-owner')
        with self.assertRaises(DomainError):
            self.service.background('other-owner', self.run_id, {
                'action': 'start', 'version': self.run_value().status_version, 'key': 'foreign'})
        with self.assertRaises(DomainError):
            self.kb.retrieve('other-owner', self.account, '白衬衫')
        self.assertEqual(self.model.calls, [])


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires real isolated PostgreSQL schema')
class PostgresRuntimeEvidenceTests(RuntimeEvidenceTests):
    def setUp(self):
        import psycopg
        self.temp = tempfile.TemporaryDirectory()
        self.base = os.environ['TEST_DATABASE_URL']
        self.schema = 'youji_test_phase2_'+uuid4().hex
        with psycopg.connect(self.base, autocommit=True) as db: db.execute('CREATE SCHEMA '+self.schema)
        self.db_url = self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema
        self.store = Store(self.db_url)
        self.prepare(); self.configure()

    def tearDown(self):
        import psycopg
        with psycopg.connect(self.base, autocommit=True) as db: db.execute('DROP SCHEMA '+self.schema+' CASCADE')
        self.temp.cleanup()

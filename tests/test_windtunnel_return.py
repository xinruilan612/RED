"""No-fee return-to-creation CAS and durable review regression."""
import copy
import json
import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4
from backend.store import Store
from backend.service import Service
from backend.provider import Config
from backend.worker import Worker
from backend.workflow import digest
from backend.contracts import DomainError
from backend.windtunnel import normalize, reading_passages


class ReturnTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'return.sqlite')
        self.prepare()

    def prepare(self):
        self.service = Service(self.store, Config())
        self.owner = 'return-owner'
        self.account = self.service.operations.read(self.owner)['accounts'][0]['id']
        created = self.service.create(self.owner, dict(topic='工具导出', audience='学生', tone='朴实', material='工具可以导出文件。', allow_hypothesis=True, mode='simulation', operations={'account_id': self.account, 'platform': 'xiaohongshu'}))
        self.creation_id = created['run_id']
        self.service.background(self.owner, self.creation_id, dict(action='start', version=created['status_version'], key=uuid4().hex))
        Worker(self.service).once()
        creation = self.store.get(self.creation_id, self.owner)
        self.assertEqual(creation.run_status, 'WAITING_USER')
        self.service.action(self.owner, self.creation_id, dict(action='accept', version=creation.status_version, key=uuid4().hex, payload={'draft_ref': creation.drafts[-1]['ref'], 'review_ref': creation.review['ref']}))
        self.before = self.store.get(self.creation_id, self.owner)
        self.wt = self.service.windtunnel.create(self.owner, {'account_id': self.account, 'import': {'run_id': self.creation_id, 'draft_ref': self.before.drafts[-1]['ref']}, 'mode': 'simulation', 'materials': [{'text': '下载目录里保存导出文件。', 'title': '官方说明'}], 'feedback': [{'text': '我找不到文件。', 'origin': '用户反馈', 'permission': True}]})
        current = self.wt.windtunnel['drafts'][-1]
        current['text'] = '先检查下载目录。\n\n' + current['text']
        current['hash'] = digest({'title': current['title'], 'text': current['text']})
        self.wt.run_status, self.wt.wait_reason = 'WAITING_USER', 'wt_recheck'
        self.persist(self.wt)
        binding = self.wt.windtunnel['import_binding']
        self.command = {'version': self.wt.status_version, 'key': uuid4().hex, 'payload': {'draft_id': current['id'], 'draft_hash': current['hash'], 'source_run_id': binding['run_id'], 'source_draft_ref': binding['draft_ref'], 'source_content_hash': binding['content_hash'], 'source_version': binding['source_version']}}

    def tearDown(self):
        self.tmp.cleanup()

    def persist(self, run):
        with self.store.connect() as db:
            db.execute('UPDATE runs SET payload=? WHERE id=?', (json.dumps(asdict(run), ensure_ascii=False), run.run_id))

    def returned(self, **kwargs):
        return self.service.return_to_creation(kwargs.get('owner', self.owner), self.wt.run_id, kwargs.get('data', self.command))

    def rejects(self, code, **kwargs):
        with self.assertRaises(DomainError) as failure:
            self.returned(**kwargs)
        self.assertEqual(failure.exception.code, code)
        self.assertEqual(asdict(self.store.get(self.creation_id, self.owner)), asdict(self.before))

    def test_new_draft_history_replay_and_explicit_worker_review(self):
        output = self.returned()
        fresh = self.store.get(self.creation_id, self.owner)
        self.assertEqual(fresh.drafts[:-1], self.before.drafts)
        self.assertEqual(fresh.reviews, self.before.reviews)
        self.assertEqual(fresh.context['acceptance_history'][-1], self.before.acceptance)
        self.assertIsNone(fresh.acceptance)
        self.assertIsNone(fresh.accepted_ref)
        self.assertIsNone(fresh.review)
        self.assertEqual(fresh.current_stage, 'reviewer')
        self.assertNotEqual(fresh.snapshot_id, self.before.snapshot_id)
        self.assertEqual(fresh.context['evidence_snapshot_history'][-1]['evidence'], self.before.context.get('evidence', []))
        self.assertEqual([e['text'] for e in fresh.context['evidence'] if e.get('source_type') == 'windtunnel_material'], ['下载目录里保存导出文件。'])
        from backend.live import material_records
        self.assertIn('下载目录里保存导出文件。', [e['text'] for e in material_records(fresh.context)])
        self.assertNotIn('我找不到文件。', [e['text'] for e in material_records(fresh.context)])
        self.assertEqual(fresh.drafts[-1]['content']['cta'], self.before.drafts[-1]['content']['cta'])
        self.assertEqual(fresh.drafts[-1]['content']['tags'], self.before.drafts[-1]['content']['tags'])
        self.assertEqual(output, self.returned())
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM live_calls').fetchone()[0], 0)
        self.assertEqual(len(fresh.drafts), 2)
        self.service.background(self.owner, self.creation_id, {'action': 'start', 'version': fresh.status_version, 'key': uuid4().hex})
        Worker(self.service).once()
        reviewed = self.store.get(self.creation_id, self.owner)
        self.assertEqual(reviewed.run_status, 'WAITING_USER')
        self.assertEqual(reviewed.wait_reason, 'final_confirmation')
        self.assertEqual(reviewed.review['draft_ref'], fresh.drafts[-1]['ref'])
        self.assertIsNone(reviewed.accepted_ref)

    def test_conflicting_source_version_and_wrong_owner(self):
        self.rejects('RESOURCE_NOT_FOUND', owner='other')
        changed = copy.deepcopy(self.command)
        changed['payload']['source_version'] += 1
        self.rejects('VERSION_CONFLICT', data=changed)
        stale = copy.deepcopy(self.before)
        stale.status_version += 1
        self.persist(stale)
        old = self.before
        self.before = stale
        self.rejects('VERSION_CONFLICT')
        self.persist(old)
        self.before = old
        self.wt.windtunnel['drafts'][-1]['text'] += '新的编辑'
        self.wt.windtunnel['drafts'][-1]['hash'] = 'different'
        self.persist(self.wt)
        self.rejects('VERSION_CONFLICT')

    def test_deleted_account_changed_or_busy_source_refused(self):
        self.store.set_visibility(self.creation_id, self.owner, True)
        self.rejects('RESOURCE_NOT_FOUND')
        self.store.set_visibility(self.creation_id, self.owner, False)
        self.before = self.store.get(self.creation_id, self.owner)
        with self.store.connect() as db:
            db.execute("UPDATE runtime_jobs SET status='queued' WHERE run_id=?", (self.creation_id,))
        self.rejects('JOB_ACTIVE')
        with self.store.connect() as db:
            db.execute("UPDATE runtime_jobs SET status='done' WHERE run_id=?", (self.creation_id,))
        original = self.store.get(self.creation_id, self.owner)
        original.context['operations']['account_id'] = 'changed'
        self.persist(original)
        self.before = original
        self.rejects('RESOURCE_NOT_FOUND')

    def test_duplicate_and_changed_key_cannot_create_second_draft(self):
        self.returned()
        changed = copy.deepcopy(self.command)
        changed['payload']['draft_hash'] = 'other'
        with self.assertRaises(DomainError) as failure:
            self.returned(data=changed)
        self.assertEqual(failure.exception.code, 'IDEMPOTENCY_CONFLICT')
        changed = copy.deepcopy(self.command)
        changed['key'] = uuid4().hex
        changed['version'] = self.store.get(self.wt.run_id, self.owner).status_version
        with self.assertRaises(DomainError) as failure:
            self.returned(data=changed)
        self.assertEqual(failure.exception.code, 'INVALID_TRANSITION')
        self.assertEqual(len(self.store.get(self.creation_id, self.owner).drafts), 2)

    def test_corrected_material_replaces_old_facts_in_live_review_context(self):
        from backend.live import material_records
        original = copy.deepcopy(self.before)
        original.context['material'] = '电池续航为12个月。'
        original.context['evidence'] = [{'source_id': 'old-number', 'source_type': 'text', 'text': '旧规格为1200mAh。'}]
        original.context['web_research'] = {'enabled': True, 'status': 'complete', 'sources': copy.deepcopy(original.context['evidence'])}
        original.context['retrieval'] = {'sources': copy.deepcopy(original.context['evidence'])}
        self.persist(original)
        state = self.wt.windtunnel
        state['sources'] = [{'id': 'corrected', 'kind': 'material', 'text': '经更正电池续航为6个月，容量为800mAh。', 'title': '更正说明', 'origin': '用户更正', 'hash': digest('经更正电池续航为6个月，容量为800mAh。')}, {'id': 'reader', 'kind': 'feedback', 'text': '读者猜测可能18个月。', 'origin': '读者猜测'}]
        self.persist(self.wt)
        self.returned()
        creation = self.store.get(self.creation_id, self.owner)
        records = material_records(creation.context)
        self.assertEqual([r['text'] for r in records], ['经更正电池续航为6个月，容量为800mAh。'])
        history = creation.context['evidence_snapshot_history'][-1]
        self.assertEqual(history['material'], '电池续航为12个月。')
        self.assertEqual(history['evidence'], original.context['evidence'])
        self.assertEqual(history['web_research'], original.context['web_research'])
        self.assertFalse(creation.context['web_research']['enabled'])
        self.assertNotIn('retrieval', creation.context)
        self.assertEqual(creation.context['windtunnel_material_binding']['policy'], 'replace_current_factual_materials')
        self.assertEqual(creation.context['windtunnel_material_binding']['material_hash'], __import__('backend.windtunnel', fromlist=['material_hash']).material_hash(self.wt))

    def test_actual_response_frozen_offline_replay_preserves_raw(self):
        from backend.workflow import Run
        fixture = json.loads((Path(__file__).parent / 'fixtures/windtunnel_real_read_type.json').read_text(encoding='utf-8'))
        run = Run(owner_id='fixture-only', snapshot_id='fixture-only', workflow_type='windtunnel', windtunnel=fixture['windtunnel'])
        raw = copy.deepcopy(fixture['response'])
        normalized = normalize(run, 'wt_read', raw)
        self.assertEqual(raw, fixture['response'])
        self.assertEqual(normalized, normalize(run, 'wt_read', {'results': raw['results']}))
        self.assertEqual(len(normalized['results']), len(raw['results']))

    def test_http_return_endpoint_csrf_owner_and_exact_replay(self):
        from fastapi.testclient import TestClient
        from backend.api import create_app
        app = create_app(self.store, Config(), origin='http://testserver', invite='')
        route = next(r for r in app.routes if getattr(r, 'path', '') == '/api/runs/{run_id}/return-to-creation')
        logged = route.dependant.dependencies[0].call
        app.dependency_overrides[logged] = lambda: {'owner': self.owner}
        with TestClient(app) as client:
            csrf = client.get('/api/session').json()['csrf']
            url = '/api/runs/' + self.wt.run_id + '/return-to-creation'
            self.assertEqual(client.post(url, json=self.command).status_code, 403)
            headers = {'Origin': 'http://testserver', 'X-CSRF-Token': csrf}
            response = client.post(url, json=self.command, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['creation']['run_id'], self.creation_id)
            self.assertEqual(client.post(url, json=self.command, headers=headers).json(), response.json())
            app.dependency_overrides[logged] = lambda: {'owner': 'other'}
            self.assertEqual(client.post(url, json=self.command, headers=headers).status_code, 404)

    def test_transport_marker_is_only_known_read_compatibility(self):
        state = self.wt.windtunnel
        state['condition_sets'] = [{'id': 'set', 'conditions': [{'id': 'q1'}]}]
        state['current_set_id'] = 'set'
        excerpt = reading_passages(state['drafts'][-1])[0]['excerpt']
        raw = {'type': 'json_object', 'results': [{'condition_id': 'q1', 'status': 'pass', 'reason': '找到了', 'answer': '检查目录', 'excerpt': excerpt}]}
        frozen = copy.deepcopy(raw)
        expected = normalize(self.wt, 'wt_read', {'results': raw['results']})
        self.assertEqual(normalize(self.wt, 'wt_read', raw), expected)
        self.assertEqual(raw, frozen)
        for bad in ({**raw, 'unexpected': True}, {**raw, 'type': 'other'}):
            with self.assertRaises(DomainError): normalize(self.wt, 'wt_read', bad)
        with self.assertRaises(DomainError): normalize(self.wt, 'wt_verify', raw)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires dedicated PostgreSQL')
class PostgresReturnTests(ReturnTests):
    def setUp(self):
        import psycopg
        self.tmp = tempfile.TemporaryDirectory()
        self.base = os.environ['TEST_DATABASE_URL']
        self.schema = 'youji_test_return_' + uuid4().hex
        with psycopg.connect(self.base, autocommit=True) as db: db.execute('CREATE SCHEMA ' + self.schema)
        self.store = Store(self.base + ('&' if '?' in self.base else '?') + 'options=-csearch_path%3D' + self.schema)
        self.prepare()

    def tearDown(self):
        import psycopg
        super().tearDown()
        with psycopg.connect(self.base, autocommit=True) as db: db.execute('DROP SCHEMA ' + self.schema + ' CASCADE')

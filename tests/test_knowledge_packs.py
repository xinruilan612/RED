"""Real database/API boundaries; model fixture tests prove wiring, not AI quality."""
import base64
import copy
import hashlib
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.contracts import DomainError
from backend.knowledge import Knowledge
from backend.knowledge_packs import PACK_ID, catalog, import_pack, manifest, preview
from backend.operations import Operations
from backend.provider import Config
from backend.service import Service
from backend.store import Store
from test_knowledge_sources import text_pdf


class KnowledgePackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'knowledge.sqlite')
        self.prepare()

    def prepare(self):
        self.kb = Knowledge(self.store)
        self.operations = Operations(self.store)
        self.owner = 'pack-owner'
        self.account = self.operations.read(self.owner)['accounts'][0]['id']

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, account=None, owner=None, packet=None):
        packet = packet or manifest(PACK_ID)
        return import_pack(self.kb, owner or self.owner, account or self.account,
                           packet['id'], packet['version'], packet['fingerprint'])

    def test_catalog_and_preview_are_read_only_original_and_fingerprinted(self):
        listing = catalog(self.kb, self.owner, self.account)
        self.assertEqual(listing[0]['count'], 3)
        packet = preview(self.kb, self.owner, self.account, PACK_ID)
        self.assertEqual(self.kb.list(self.owner, self.account), [])
        for doc in packet['documents']:
            self.assertEqual(doc['fingerprint'], hashlib.sha256(doc['text'].encode('utf-8')).hexdigest())
            for field in ('author', 'license', 'boundary', 'published_at', 'source_label'):
                self.assertTrue(doc[field])
            self.assertIn('项目', doc['text'])
            self.assertEqual(doc['source_type'], 'project_guide')
        digest = packet.pop('fingerprint')
        self.assertEqual(digest, hashlib.sha256(json.dumps(packet, ensure_ascii=False, sort_keys=True,
                                                          separators=(',', ':')).encode('utf-8')).hexdigest())

    def test_import_reimport_and_versions_preserve_provenance(self):
        first = self.install()
        second = self.install()
        self.assertEqual((first['created'], first['skipped'], first['conflict']), (3, 0, 0))
        self.assertEqual((second['created'], second['skipped'], second['conflict']), (0, 3, 0))
        self.assertEqual(len(self.kb.list(self.owner, self.account)), 3)
        for result in first['documents']:
            stored = self.kb.get(self.owner, self.account, result['document_id'])
            raw = base64.b64decode(stored['original_base64'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), stored['fingerprint'])
            self.assertEqual(stored['metadata']['pack']['fingerprint'], first['fingerprint'])
            self.assertEqual(stored['metadata']['published_at'], '2026-09-22')
            self.assertIn('不改变项目代码许可', stored['metadata']['license'])
            self.assertEqual(len(stored['versions']), 1)

    def test_concurrent_import_is_serialized_without_duplicate_documents(self):
        barrier = threading.Barrier(4)
        def concurrent():
            barrier.wait(timeout=10)
            return self.install()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: concurrent(), range(4)))
        self.assertEqual(sum(r['created'] for r in results), 3)
        self.assertEqual(sum(r['skipped'] for r in results), 9)
        self.assertEqual(sum(r['conflict'] for r in results), 0)
        self.assertEqual(len(self.kb.list(self.owner, self.account)), 3)

    def test_user_edits_conflict_and_deleted_items_never_revive(self):
        installed = self.install()['documents']
        changed = self.kb.save(self.owner, dict(account_id=self.account, title='我的修改', text='这是用户改写后的正文。',
                                               document_id=installed[0]['document_id'], expected_version=1))
        self.kb.delete(self.owner, self.account, installed[1]['document_id'], 1)
        result = self.install()
        self.assertEqual((result['created'], result['skipped'], result['conflict']), (0, 1, 2))
        self.assertEqual(self.kb.get(self.owner, self.account, changed['id'])['fingerprint'], changed['fingerprint'])
        self.assertEqual(len(self.kb.list(self.owner, self.account)), 2)
        with self.assertRaises(DomainError):
            self.kb.get(self.owner, self.account, installed[1]['document_id'], 1)

    def test_import_and_user_edit_race_preserves_user_revision(self):
        identity = self.install()['documents'][0]['document_id']
        barrier = threading.Barrier(2)
        def edit():
            barrier.wait(timeout=10)
            return self.kb.save(self.owner, dict(account_id=self.account, title='用户最新版', text='不得覆盖的用户资料正文。',
                                                document_id=identity, expected_version=1))
        def install():
            barrier.wait(timeout=10)
            return self.install()
        with ThreadPoolExecutor(max_workers=2) as pool:
            edited, imported = pool.submit(edit), pool.submit(install)
            edited.result(timeout=20)
            result = imported.result(timeout=20)
        self.assertEqual(result['created'], 0)
        self.assertEqual(result['skipped'] + result['conflict'], 3)
        self.assertEqual(self.kb.get(self.owner, self.account, identity)['title'], '用户最新版')

    def test_package_version_changes_and_duplicate_content_do_not_overwrite(self):
        packet = manifest(PACK_ID)
        for version, fingerprint in ((True, packet['fingerprint']), (0, packet['fingerprint']),
                                     (2, packet['fingerprint']), (1, 'stale')):
            with self.assertRaises(DomainError):
                import_pack(self.kb, self.owner, self.account, PACK_ID, version, fingerprint)
        doc = packet['documents'][0]
        original = self.kb.save(self.owner, dict(account_id=self.account, title='我的原文', text=doc['text']))
        result = self.install()
        self.assertEqual((result['created'], result['skipped'], result['conflict']), (2, 0, 1))
        self.assertEqual(self.kb.get(self.owner, self.account, original['id'])['title'], '我的原文')
        newer = copy.deepcopy(packet)
        newer['version'] = 2
        newer['fingerprint'] = 'new-manifest-fixture'
        with patch('backend.knowledge_packs.manifest', return_value=newer):
            result = self.install(packet=newer)
        self.assertEqual((result['created'], result['skipped'], result['conflict']), (0, 0, 3))

    def test_manual_duplicate_history_after_edit_blocks_pack_reintroduction(self):
        doc = manifest(PACK_ID)['documents'][0]
        manual = self.kb.save(self.owner, dict(account_id=self.account, title='手动粘贴的原文', text=doc['text']))
        initial = self.install()
        self.assertEqual((initial['created'], initial['conflict']), (2, 1))
        changed = self.kb.save(self.owner, dict(account_id=self.account, title='用户修订', text='只保留这份用户修订正文。',
                                              document_id=manual['id'], expected_version=1))
        result = self.install()
        self.assertEqual((result['created'], result['skipped'], result['conflict']), (0, 2, 1))
        self.assertIn('修订', result['documents'][0]['reason'])
        current = self.kb.get(self.owner, self.account, manual['id'])
        self.assertEqual(current['fingerprint'], changed['fingerprint'])
        self.assertEqual(current['version'], 2)
        self.assertEqual(self.kb.get(self.owner, self.account, manual['id'], 1)['fingerprint'], doc['fingerprint'])
        with self.store.connect() as db:
            count = db.execute('SELECT COUNT(*) FROM knowledge_versions WHERE fingerprint=?', (doc['fingerprint'],)).fetchone()[0]
        self.assertEqual(count, 1, 'Do not create a separate document for an obsolete manual original')
        self.assertEqual(len(self.kb.list(self.owner, self.account)), 3)

    def test_manual_duplicate_tombstone_blocks_pack_reintroduction(self):
        doc = manifest(PACK_ID)['documents'][0]
        manual = self.kb.save(self.owner, dict(account_id=self.account, title='手动粘贴的原文', text=doc['text']))
        initial = self.install()
        self.assertEqual((initial['created'], initial['conflict']), (2, 1))
        self.kb.delete(self.owner, self.account, manual['id'], 1)
        result = self.install()
        self.assertEqual((result['created'], result['skipped'], result['conflict']), (0, 2, 1))
        self.assertIn('移除', result['documents'][0]['reason'])
        self.assertEqual(len(self.kb.list(self.owner, self.account)), 2)
        with self.assertRaises(DomainError):
            self.kb.get(self.owner, self.account, manual['id'])
        with self.store.connect() as db:
            row = db.execute('SELECT status,version FROM knowledge_documents WHERE id=?', (manual['id'],)).fetchone()
            count = db.execute('SELECT COUNT(*) FROM knowledge_versions WHERE fingerprint=?', (doc['fingerprint'],)).fetchone()[0]
        self.assertEqual(row, ('deleted', 1))
        self.assertEqual(count, 1, 'Do not recreate deleted manual text under a deterministic pack ID')

    def test_owner_and_account_isolation_on_every_pack_path(self):
        stranger = self.operations.read('stranger')['accounts'][0]['id']
        for action in (lambda: catalog(self.kb, 'stranger', self.account),
                       lambda: preview(self.kb, 'stranger', self.account, PACK_ID),
                       lambda: self.install(owner='stranger', account=self.account)):
            with self.assertRaises(DomainError) as raised:
                action()
            self.assertEqual(raised.exception.code, 'RESOURCE_NOT_FOUND')
        first = self.install()
        second = self.install(owner='stranger', account=stranger)
        self.assertTrue({d['document_id'] for d in first['documents']}.isdisjoint(
                        {d['document_id'] for d in second['documents']}))
        state = self.operations.command(self.owner, dict(action='load_sample', payload={}, version=0, key='sample'))
        other_account = next(a['id'] for a in state['accounts'] if a.get('demo_sample'))
        self.assertEqual(self.kb.list(self.owner, other_account), [])
        self.assertEqual(self.install(account=other_account)['created'], 3)

    def test_demo_only_policy_uses_server_account_flag_not_client_claim(self):
        packet = manifest(PACK_ID)
        packet['demo_only'] = True  # Exercise future fixture packs without shipping fake business facts.
        with patch('backend.knowledge_packs.manifest', return_value=packet):
            self.assertFalse(catalog(self.kb, self.owner, self.account)[0]['available'])
            for action in (lambda: preview(self.kb, self.owner, self.account, PACK_ID), lambda: self.install(packet=packet)):
                with self.assertRaises(DomainError) as raised:
                    action()
                self.assertEqual(raised.exception.code, 'FORBIDDEN')
            state = self.operations.command(self.owner, dict(action='load_sample', payload={}, version=0, key='sample'))
            account = next(a['id'] for a in state['accounts'] if a.get('demo_sample'))
            self.assertEqual(self.install(account=account, packet=packet)['created'], 3)

    def test_import_rolls_back_as_one_transaction(self):
        original = self.kb._write_version
        calls = 0
        def failure(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('simulated disk failure')
            return original(*args, **kwargs)
        with patch.object(self.kb, '_write_version', side_effect=failure), self.assertRaises(RuntimeError):
            self.install()
        self.assertEqual(self.kb.list(self.owner, self.account), [])
        self.assertEqual(self.install()['created'], 3)

    def test_capacity_rejects_entire_pack_without_partial_writes(self):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for number in range(98):
                text = '已有资料 ' + str(number)
                self.kb._write_version(db, self.owner, self.account, str(uuid4()), 1, text, text.encode('utf-8'),
                                       [(1, text)], 'fixture.txt', 'text', '', {}, 1)
        with self.assertRaises(DomainError) as raised:
            self.install()
        self.assertEqual(raised.exception.code, 'QUOTA_EXCEEDED')
        self.assertEqual(len(self.kb.list(self.owner, self.account)), 98)

    def test_old_version_keeps_original_pages_source_and_fingerprint(self):
        raw = text_pdf()
        old = self.kb.save(self.owner, dict(account_id=self.account, title='原文', filename='care.pdf',
                                           file_base64=base64.b64encode(raw).decode('ascii')),
                           source_url='https://example.com/old', metadata={'published_at': '2025-01-01', 'author': '旧作者'})
        new = self.kb.save(self.owner, dict(account_id=self.account, title='改写', text='现在的资料与旧版不同。',
                                           document_id=old['id'], expected_version=1),
                           source_type='web', source_url='https://example.com/new', metadata={'published_at': '2026-01-01'})
        loaded = self.kb.get(self.owner, self.account, old['id'], 1)
        self.assertEqual(loaded['fingerprint'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(base64.b64decode(loaded['original_base64']), raw)
        self.assertEqual(loaded['source_url'], 'https://example.com/old')
        self.assertEqual(loaded['source_type'], 'upload')
        self.assertEqual(loaded['metadata']['published_at'], '2025-01-01')
        self.assertEqual({c['page'] for c in loaded['chunks']}, {1, 2})
        self.assertTrue(loaded['read_only'])
        self.assertEqual(loaded['current_version'], 2)
        self.assertEqual(self.kb.get(self.owner, self.account, old['id'])['fingerprint'], new['fingerprint'])
        self.assertTrue(self.kb.retrieve(self.owner, self.account, 'cold water')['insufficient'])

    def test_historical_missing_metadata_is_not_backfilled_from_current_source(self):
        old = self.kb.save(self.owner, dict(account_id=self.account, title='旧资料', text='旧版资料正文。'))
        self.kb.save(self.owner, dict(account_id=self.account, title='今日标题', text='当前正文。', document_id=old['id'], expected_version=1),
                     source_type='web', source_url='https://example.com/today')
        with self.store.connect() as db:
            db.execute('UPDATE knowledge_versions SET metadata=? WHERE document_id=? AND version=1', ('{}', old['id']))
        loaded = self.kb.get(self.owner, self.account, old['id'], 1)
        self.assertEqual(loaded['source_type'], 'unknown')
        self.assertEqual(loaded['source_url'], '')
        self.assertEqual(loaded['title'], '标题未记录')
        self.assertIsNone(loaded['stored_at'])
        self.assertFalse(loaded['source_recorded'])

    def test_version_validation_and_cross_owner_lookup(self):
        identity = self.install()['documents'][0]['document_id']
        for version in (0, -1, True, '1', 1.5, 2147483648):
            with self.subTest(version=version), self.assertRaises(DomainError) as raised:
                self.kb.get(self.owner, self.account, identity, version)
            self.assertEqual(raised.exception.code, 'INVALID_INPUT')
        with self.assertRaises(DomainError) as raised:
            self.kb.get(self.owner, self.account, identity, 2)
        self.assertEqual(raised.exception.code, 'RESOURCE_NOT_FOUND')
        stranger = self.operations.read('stranger')['accounts'][0]['id']
        with self.assertRaises(DomainError):
            self.kb.get('stranger', stranger, identity, 1)

    def test_retrieval_task_and_all_four_roles_share_frozen_pack_evidence(self):
        from test_live_provider import FixtureModel
        self.install()
        model = FixtureModel()
        service = Service(self.store, Config('fixture-not-real'), model)
        result = service.create(self.owner, dict(mode='live', topic='资料版本与证据回查', audience='整理原文资料的创作者',
            tone='清楚', material='', scenario='standard', allow_hypothesis=True, knowledge={'enabled': True},
            operations={'account_id': self.account, 'platform': 'xiaohongshu', 'account': '我的账号'}))
        frozen = copy.deepcopy(result['context']['evidence'])
        self.assertTrue(frozen)
        self.assertTrue(all(s['fingerprint'] and s['metadata']['pack']['id'] == PACK_ID for s in frozen))
        for source in {s['document_id']: s for s in frozen}.values():
            self.kb.delete(self.owner, self.account, source['document_id'], source['version'])
        for _ in range(7):
            result = service.action(self.owner, result['run_id'], dict(action='next', version=result['status_version'],
                                                                      key=str(uuid4()), payload={}))
        self.assertEqual(result['wait_reason'], 'final_confirmation')
        self.assertEqual(result['context']['evidence'], frozen)
        self.assertEqual({node['agent'] for node in result['node_runs']}, {'audience', 'research', 'content', 'reviewer'})
        expected = [(s['source_id'], s['text'], s['version']) for s in frozen]
        for node in result['node_runs']:
            self.assertEqual([(s['source_id'], s['text'], s['version']) for s in node['input']['materials']], expected)
            for source in node['input']['materials']:
                self.assertIn('有迹项目自编资料', source['verification'])
                self.assertIn('不是平台官方规则、行业标准或用户亲历事实', source['verification'])

    def test_http_routes_csrf_permissions_preview_and_version_validation(self):
        app = create_app(self.store, Config(), origin='http://testserver', settings_override={})
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/knowledge/packs', params={'account_id': self.account}).status_code, 401)
            csrf = client.get('/api/session').json()['csrf']
            def post(path, data):
                return client.post(path, json=data, headers={'Origin': 'http://testserver', 'X-CSRF-Token': csrf})
            registered = post('/api/auth/register', dict(username='pack_reader', password='Fixture-password'))
            self.assertEqual(registered.status_code, 200, registered.text)
            csrf = registered.json()['csrf']
            account = client.get('/api/operations').json()['accounts'][0]['id']
            self.assertEqual(client.get('/api/knowledge/packs', params={'account_id': self.account}).status_code, 404)
            listing = client.get('/api/knowledge/packs', params={'account_id': account})
            self.assertEqual(listing.status_code, 200, listing.text)
            packet = client.get('/api/knowledge/packs/'+PACK_ID, params={'account_id': account}).json()
            self.assertEqual(len(packet['documents']), 3)
            data = dict(account_id=account, version=packet['version'], fingerprint=packet['fingerprint'])
            path = '/api/knowledge/packs/'+PACK_ID+'/import'
            self.assertEqual(client.post(path, json=data).status_code, 403)
            self.assertEqual(post(path, data | {'is_demo': True}).status_code, 400)
            self.assertEqual(post(path, data | {'account_id': self.account}).status_code, 404)
            response = post(path, data)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['created'], 3)
            identity = response.json()['documents'][0]['document_id']
            url = '/api/knowledge/'+identity
            for version in ('0', '-1', '1.5', '1.0', 'true', '2147483648', '9'*30, ''):
                self.assertEqual(client.get(url, params={'account_id': account, 'version': version}).status_code, 400, version)
            self.assertEqual(client.get(url, params={'account_id': account, 'version': '2'}).status_code, 404)
            self.assertEqual(client.get(url, params={'account_id': account, 'version': '1'}).json()['version'], 1)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'PostgreSQL integration requires TEST_DATABASE_URL')
class PostgresKnowledgePackTests(KnowledgePackTests):
    def setUp(self):
        import psycopg
        self.tmp = tempfile.TemporaryDirectory()
        self.schema = 'youji_test_' + uuid4().hex
        self.base = os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base, autocommit=True) as db:
            db.execute('CREATE SCHEMA ' + self.schema)
        self.store = Store(self.base + ('&' if '?' in self.base else '?') + 'options=-csearch_path%3D' + self.schema)
        self.prepare()

    def tearDown(self):
        import psycopg
        super().tearDown()
        with psycopg.connect(self.base, autocommit=True) as db:
            db.execute('DROP SCHEMA ' + self.schema + ' CASCADE')


if __name__ == '__main__':
    unittest.main()

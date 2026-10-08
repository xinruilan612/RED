"""Real PostgreSQL correction transactions; never touches the user's run."""
from copy import deepcopy
from dataclasses import asdict
from io import BytesIO
import json
import os
import unittest
from uuid import uuid4
from zipfile import ZipFile

from backend.confirmed_corrections import remove_confirmed_paragraph
from backend.contracts import DomainError
from backend.execution import Executor
from backend.media_exports import export_run
from backend.provider import Config
from backend.store import Store
from backend.workflow import digest


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires actual PostgreSQL TEST_DATABASE_URL')
class ConfirmedCorrectionsTests(unittest.TestCase):
    paragraph = '本文据罗技官方公开资料整理，非亲测、非品牌合作。'

    def setUp(self):
        import psycopg
        self.base = os.environ['TEST_DATABASE_URL']
        self.schema = 'youji_correction_' + uuid4().hex
        with psycopg.connect(self.base, autocommit=True) as db:
            db.execute('CREATE SCHEMA ' + self.schema)
        self.addCleanup(self.drop_schema)
        self.store = Store(self.base + ('&' if '?' in self.base else '?') + 'options=-csearch_path%3D' + self.schema)
        Executor(self.store, Config())
        self.run = self.store.create('owner', 'snapshot')
        content = {'selected_title': '鼠标怎么选', 'body': '先核对电脑接口。\n\n' + self.paragraph + '\n\n小巧不代表人人合手。',
                   'tags': ['鼠标'], 'cta': '你的电脑有哪些接口？'}
        self.run.drafts = [{'ref': 'draft@4', 'content': content, 'content_hash': digest(content),
                            'snapshot_id': 'snapshot', 'actor': 'content'}]
        self.run.accepted_ref = 'draft@4'
        self.run.acceptance = {'mode': 'manual_override', 'draft_ref': 'draft@4', 'snapshot_id': 'snapshot',
                               'content_hash': digest(content), 'acknowledged_issues': [{'id': 'old-issue'}]}
        self.run.reviews = [{'ref': 'review@3', 'decision': 'revise'}]
        self.run.prior_review = deepcopy(self.run.reviews[0])
        self.run.run_status = 'SUCCEEDED'
        self.run.event('human.accepted', acceptance=deepcopy(self.run.acceptance))
        self.save()

    def drop_schema(self):
        import psycopg
        with psycopg.connect(self.base, autocommit=True) as db:
            db.execute('DROP SCHEMA ' + self.schema + ' CASCADE')

    def save(self):
        with self.store.connect() as db:
            db.execute('UPDATE runs SET payload=? WHERE id=?', (json.dumps(asdict(self.run)), self.run.run_id))

    def correct(self, **overrides):
        args = dict(store=self.store, owner='owner', run_id=self.run.run_id,
                    expected_version=0, expected_ref='draft@4', paragraph=self.paragraph, key='correction')
        args.update(overrides)
        return remove_confirmed_paragraph(**args)

    def assert_code(self, code, **overrides):
        before = asdict(self.store.get(self.run.run_id, 'owner'))
        with self.assertRaises(DomainError) as caught:
            self.correct(**overrides)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(asdict(self.store.get(self.run.run_id, 'owner')), before)

    def test_new_manual_version_preserves_history_and_export(self):
        old = deepcopy(self.run)
        result = self.correct()
        self.assertEqual(result.run_status, 'SUCCEEDED')
        self.assertEqual(result.status_version, 1)
        self.assertEqual(result.drafts[:-1], old.drafts)
        self.assertEqual(result.reviews, old.reviews)
        self.assertEqual(result.events[:-2], old.events)
        self.assertEqual(result.events[-1]['payload']['old_acceptance'], old.acceptance)
        self.assertEqual(result.acceptance['mode'], 'manual_override')
        self.assertIsNone(result.acceptance['review_ref'])
        self.assertIsNone(result.review)
        self.assertEqual(result.drafts[-1]['actor'], 'user')
        expected = deepcopy(old.drafts[-1]['content'])
        expected['body'] = '先核对电脑接口。\n\n小巧不代表人人合手。'
        self.assertEqual(result.drafts[-1]['content'], expected)
        self.assertEqual(result.acceptance['content_hash'], digest(expected))
        blob, _, _ = export_run(result, kind='images')
        with ZipFile(BytesIO(blob)) as archive:
            self.assertNotIn(self.paragraph, archive.read('caption.txt').decode())
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['draft_ref'], result.accepted_ref)
            self.assertEqual(manifest['acceptance']['mode'], 'manual_override')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM live_calls').fetchone()[0], 0)

    def test_retry_idempotent_and_key_conflict(self):
        first = self.correct()
        self.assertEqual(asdict(self.correct()), asdict(first))
        self.assertEqual(len(self.store.get(self.run.run_id, 'owner').drafts), 2)
        self.assert_code('IDEMPOTENCY_CONFLICT', paragraph='另一个段落')
        self.assert_code('RESOURCE_NOT_FOUND', owner='someone-else')

    def test_version_ref_and_confirmed_hash_guards(self):
        self.assert_code('VERSION_CONFLICT', expected_version=1)
        self.assert_code('VERSION_CONFLICT', expected_ref='draft@3')
        self.run.drafts[-1]['content']['body'] += '损坏'
        self.save()
        self.assert_code('VERSION_CONFLICT')

    def test_only_one_exact_independent_nonempty_paragraph(self):
        self.assert_code('INVALID_INPUT', paragraph='非亲测')
        for body in (self.paragraph, self.paragraph + '\n\n' + self.paragraph,
                     '正文\n' + self.paragraph, '正文' + self.paragraph):
            self.run.drafts[-1]['content']['body'] = body
            self.run.drafts[-1]['content_hash'] = digest(self.run.drafts[-1]['content'])
            self.run.acceptance['content_hash'] = self.run.drafts[-1]['content_hash']
            self.save()
            self.assert_code('INVALID_INPUT')

    def test_active_job_blocks_and_rolls_back(self):
        with self.store.connect() as db:
            db.execute('INSERT INTO runtime_jobs(id,run_id,owner,status,updated,thread_id,policy) VALUES(?,?,?,?,?,?,?)',
                       ('job', self.run.run_id, 'owner', 'queued', 0, 'thread', '{}'))
        for status in ('queued', 'running', 'pausing'):
            with self.store.connect() as db:
                db.execute('UPDATE runtime_jobs SET status=?', (status,))
            self.assert_code('JOB_ACTIVE')

    def test_running_model_blocks_and_rolls_back(self):
        with self.store.connect() as db:
            db.execute('INSERT INTO live_steps(run_id,version,key,state) VALUES(?,?,?,?)', (self.run.run_id, 0, 'call', 'running'))
        self.assert_code('JOB_ACTIVE')

    def test_nonconfirmed_and_newer_draft_are_rejected(self):
        self.run.run_status = 'RUNNING'
        self.save()
        self.assert_code('INVALID_TRANSITION')
        self.run.run_status = 'SUCCEEDED'
        newer = deepcopy(self.run.drafts[0]); newer['ref'] = 'draft@5'
        self.run.drafts.append(newer)
        self.save()
        self.assert_code('VERSION_CONFLICT')


class ConfirmedCorrectionsSqliteTests(ConfirmedCorrectionsTests):
    __unittest_skip__ = False

    def setUp(self):
        import tempfile
        from pathlib import Path
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name) / 'corrections.sqlite3')
        Executor(self.store, Config())
        self.run = self.store.create('owner', 'snapshot')
        content = {'selected_title': '鼠标怎么选', 'body': '先核对电脑接口。\n\n' + self.paragraph + '\n\n小巧不代表人人合手。',
                   'tags': ['鼠标'], 'cta': '你的电脑有哪些接口？'}
        self.run.drafts = [{'ref': 'draft@4', 'content': content, 'content_hash': digest(content),
                            'snapshot_id': 'snapshot', 'actor': 'content'}]
        self.run.accepted_ref = 'draft@4'
        self.run.acceptance = {'mode': 'manual_override', 'draft_ref': 'draft@4', 'snapshot_id': 'snapshot',
                               'content_hash': digest(content), 'acknowledged_issues': [{'id': 'old-issue'}]}
        self.run.reviews = [{'ref': 'review@3', 'decision': 'revise'}]
        self.run.prior_review = deepcopy(self.run.reviews[0])
        self.run.run_status = 'SUCCEEDED'
        self.run.event('human.accepted', acceptance=deepcopy(self.run.acceptance))
        self.save()

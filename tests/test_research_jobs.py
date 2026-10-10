import tempfile
import time
import unittest
import os
from pathlib import Path
from uuid import uuid4

from backend.contracts import DomainError
from backend.migrations import upgrade
from backend.operations import Operations
from backend.research_jobs import ResearchJobs
from backend.store import Store


class ResearchJobsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name)/'jobs.sqlite')
        self.prepare()

    def prepare(self):
        upgrade(self.store)
        self.account = Operations(self.store).read('owner')['accounts'][0]['id']
        self.calls, self.reads = [], []
        self.results = [dict(title='保湿产品参考', url='https://example.com/a')]
        test = self
        class Searcher:
            def search(self, owner, query, provider, targets):
                test.calls.append(query)
                return {'results': test.results}
        def reader(url):
            self.reads.append(url)
            return dict(url=url, title='保湿产品参考', text='合法公开资料的正文，仅供研究参考，不代表平台爆款，资料来源与事实真实性应单独核验。'+url,
                        fetched_at='2026-01-01T00:00:00+00:00', verification='公开正文')
        self.jobs = ResearchJobs(self.store, searcher=Searcher(), reader=reader)

    def tearDown(self):
        self.temp.cleanup()

    def packet(self, **extra):
        return dict(account_id=self.account, queries=['保湿产品'], provider='bing', targets=['web'],
                    evidence_role='expression_reference', permission_confirmed=True, key='one', **extra)

    def test_idempotency_owner_scope_and_report_only_this_task(self):
        first = self.jobs.create('owner', self.packet())
        self.assertEqual(self.jobs.create('owner', self.packet())['id'], first['id'])
        changed = self.packet(); changed['queries'] = ['另外产品']
        with self.assertRaises(DomainError): self.jobs.create('owner', changed)
        with self.assertRaises(DomainError): self.jobs.get('other', first['id'])
        with self.assertRaises(DomainError): self.jobs.list('other', self.account)
        self.assertTrue(self.jobs.once())
        final = self.jobs.get('owner', first['id'])
        self.assertEqual(final['status'], 'done')
        self.assertEqual(len(final['documents']), 1)
        self.assertNotIn('token', final)
        self.assertEqual(self.jobs.export('owner', first['id'])['count'], 1)
        self.assertFalse(self.jobs.once())
        self.assertEqual(len(self.calls), 1)
        self.results = [dict(title='另一来源', url='https://example.com/b')]
        next_data = self.packet(); next_data['key'] = 'two'
        second = self.jobs.create('owner', next_data)
        self.jobs.once()
        report = self.jobs.export('owner', second['id'])
        self.assertEqual(report['count'], 1)
        self.assertNotIn('https://example.com/a', report['content'])

    def test_restricted_sources_are_leads_and_never_read(self):
        self.results = [dict(title='小红书线索', url='https://www.xiaohongshu.com/explore/a')]
        job = self.jobs.create('owner', self.packet()); self.jobs.once()
        final = self.jobs.get('owner', job['id'])
        self.assertEqual(self.reads, [])
        self.assertEqual(final['status'], 'partial')
        self.assertEqual(final['reads'][0]['status'], 'permission_required')
        self.assertIsNone(final['reads'][0]['heat'])
        self.assertEqual(self.jobs.export('owner', job['id'])['count'], 0)

    def test_six_page_and_three_document_bounds_and_url_dedup(self):
        self.results = [dict(title=str(i), url='https://example.com/'+str(i)) for i in range(8)]
        packet = self.packet(); packet['queries'] = ['保湿产品', '清洁产品']
        job = self.jobs.create('owner', packet); self.jobs.once()
        final = self.jobs.get('owner', job['id'])
        self.assertEqual(len(self.reads), 3)
        self.assertEqual(len(final['documents']), 3)
        self.assertEqual(len(final['reads']), 8)
        self.assertEqual(len(self.calls), 2)

    def test_read_failure_records_are_sanitized_and_bounded(self):
        self.results = [dict(title=str(i), url='https://example.com/'+str(i)) for i in range(8)]
        def fail(url):
            self.reads.append(url)
            raise ValueError('secret credential provider payload')
        self.jobs.reader = fail
        job = self.jobs.create('owner', self.packet()); self.jobs.once()
        final = self.jobs.get('owner', job['id'])
        self.assertEqual(len(self.reads), 6)
        self.assertNotIn('credential', str(final))
        self.assertEqual(final['status'], 'failed')
        self.assertEqual(final['outcome'], 'detail_failed')

    def test_cancel_while_reading_discards_late_body(self):
        job = self.jobs.create('owner', self.packet())
        reader = self.jobs.reader
        def cancel_then_return(url):
            self.jobs.cancel('owner', job['id'])
            return reader(url)
        self.jobs.reader = cancel_then_return
        self.jobs.once()
        self.assertEqual(self.jobs.get('owner', job['id'])['status'], 'cancelled')
        self.assertEqual(self.jobs.cases.list('owner', self.account), [])
        report = self.jobs.export('owner', job['id'])
        self.assertIn('cancelled', report['content'])
        self.assertIn('保湿产品', report['content'])
        self.assertEqual(len(self.calls), 1)

    def test_crash_expiry_is_interrupted_never_replayed(self):
        job = self.jobs.create('owner', self.packet())
        claim = self.jobs._claim()
        with self.store.connect() as db:
            db.execute('UPDATE research_jobs SET lease_until=? WHERE id=?', (time.time()-1, job['id']))
        self.assertFalse(self.jobs.once())
        self.assertEqual(self.jobs.get('owner', job['id'])['status'], 'interrupted')
        self.assertEqual(self.calls, [])
        with self.assertRaises(DomainError): self.jobs._change(claim)

    def test_cancel_between_body_and_transaction_guard_prevents_insert(self):
        job = self.jobs.create('owner', self.packet())
        original = self.jobs.cases.from_article
        def cancelled(*args, **kwargs):
            self.jobs.cancel('owner', job['id'])
            return original(*args, **kwargs)
        self.jobs.cases.from_article = cancelled
        self.jobs.once()
        self.assertEqual(self.jobs.cases.list('owner', self.account), [])
        self.assertEqual(self.jobs.get('owner', job['id'])['documents'], [])

    def test_document_and_job_link_rollback_together(self):
        job = self.jobs.create('owner', self.packet())
        original = self.jobs.cases.from_article
        def fail_link(*args, **kwargs):
            saved = kwargs['transaction_saved']
            def fail(db, identity, version):
                saved(db, identity, version)
                raise ValueError('failure after linking')
            kwargs['transaction_saved'] = fail
            return original(*args, **kwargs)
        self.jobs.cases.from_article = fail_link
        self.jobs.once()
        self.assertEqual(self.jobs.cases.list('owner', self.account), [])
        self.assertEqual(self.jobs.get('owner', job['id'])['documents'], [])


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'PostgreSQL integration requires TEST_DATABASE_URL')
class PostgresResearchJobsTests(ResearchJobsTests):
    def setUp(self):
        import psycopg
        self.schema = 'youji_test_research_jobs_'+uuid4().hex
        self.base = os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base, autocommit=True) as db:
            db.execute('CREATE SCHEMA '+self.schema)
        self.store = Store(self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema)
        self.prepare()

    def tearDown(self):
        import psycopg
        with psycopg.connect(self.base, autocommit=True) as db:
            db.execute('DROP SCHEMA '+self.schema+' CASCADE')


if __name__ == '__main__':
    unittest.main()

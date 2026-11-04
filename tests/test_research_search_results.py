import json
import unittest
from test_research_jobs import ResearchJobsTests
from backend.contracts import DomainError

class ResearchSearchResultsTests(unittest.TestCase):
    setUp=ResearchJobsTests.setUp
    prepare=ResearchJobsTests.prepare
    packet=ResearchJobsTests.packet
    tearDown=ResearchJobsTests.tearDown

    def test_leads_saved_before_read_and_visible_after_all_reads_fail(self):
        self.results=[{'title':str(i),'url':f'https://example.com/{i}','snippet':'仅搜索摘要'} for i in range(8)]
        job=self.jobs.create('owner',self.packet())
        def fail(url):
            live=self.jobs.get('owner',job['id'])
            self.assertEqual(len(live['search_results']),8)
            self.assertEqual(live['search_result_count'],8)
            raise DomainError('SOURCE_UNAVAILABLE','fixture')
        self.jobs.reader=fail;self.jobs.once()
        final=self.jobs.get('owner',job['id'])
        self.assertEqual(len(final['search_results']),8)
        self.assertTrue(all(s['body_read'] is False for s in final['search_results']))
        self.assertEqual(final['candidates'],[])
        self.assertEqual(final['documents'],[])

    def test_free_retry_uses_stored_leads_and_never_searches_again(self):
        reader=self.jobs.reader
        def fail(url):raise DomainError('SOURCE_UNAVAILABLE','fixture')
        self.jobs.reader=fail
        job=self.jobs.create('owner',self.packet(confirmation_required=True));self.jobs.once()
        calls=list(self.calls)
        self.jobs.reader=reader
        queued=self.jobs.retry_reads('owner',job['id'])
        self.assertEqual(queued['status'],'queued')
        self.assertEqual(self.jobs.retry_reads('owner',job['id'])['read_retry_count'],1)
        self.jobs.once();final=self.jobs.get('owner',job['id'])
        self.assertEqual(self.calls,calls)
        self.assertEqual(len(final['candidates']),1)
        self.assertEqual(final['documents'],[])
        self.assertEqual(len(final['read_attempts_history']),1)

    def test_legacy_missing_links_are_reported_without_invention(self):
        job=self.jobs.create('owner',self.packet())
        with self.store.connect() as db:
            p=json.loads(db.execute('SELECT payload FROM research_jobs WHERE id=?',(job['id'],)).fetchone()[0])
            p.pop('search_results');p['attempts']=[{'query':'保湿产品','status':'done','results':8}]
            p['items']=[{'url':f'https://example.com/{i}','title':str(i),'status':'failed','error':'SOURCE_UNAVAILABLE','query':'保湿产品'} for i in range(5)]
            db.execute("UPDATE research_jobs SET status='failed',payload=? WHERE id=?",(json.dumps(p),job['id']))
        public=self.jobs.get('owner',job['id'])
        self.assertEqual(public['search_result_count'],8)
        self.assertEqual(len(public['search_results']),5)
        self.assertEqual(public['search_result_retention'],'legacy_partial')
        self.jobs.retry_reads('owner',job['id'])
        self.assertEqual(self.jobs.get('owner',job['id'])['search_result_retention'],'legacy_partial')
        with self.assertRaises(DomainError):self.jobs.retry_reads('other',job['id'])

    def test_active_and_cancelled_jobs_cannot_trigger_read_retry(self):
        job=self.jobs.create('owner',self.packet())
        with self.assertRaises(DomainError):self.jobs.retry_reads('owner',job['id'])
        self.jobs.cancel('owner',job['id'])
        with self.assertRaises(DomainError):self.jobs.retry_reads('owner',job['id'])

import unittest
from test_research_jobs import ResearchJobsTests
from backend.contracts import DomainError


class ResearchReadFallbackTests(unittest.TestCase):
    setUp=ResearchJobsTests.setUp
    prepare=ResearchJobsTests.prepare
    packet=ResearchJobsTests.packet
    tearDown=ResearchJobsTests.tearDown

    def test_403_does_not_occupy_body_slots_and_remaining_saved_leads_are_read(self):
        self.results=[dict(title=str(i),url=f'https://example.com/{i}') for i in range(8)]
        reader=self.jobs.reader
        def read(url):
            if url.endswith(('/0','/1','/2','/3','/4')):
                self.reads.append(url)
                raise DomainError('SOURCE_HTTP_403','程序请求被拒绝')
            return reader(url)
        self.jobs.reader=read
        job=self.jobs.create('owner',self.packet(confirmation_required=True));self.jobs.once()
        final=self.jobs.get('owner',job['id'])
        self.assertEqual(len(self.reads),8)
        self.assertEqual(len(final['candidates']),3)
        failed=[i for i in final['items'] if i['status']=='failed']
        self.assertEqual(len(failed),5)
        self.assertTrue(all(i['browser_openable'] and i['diagnostic_collapsed'] for i in failed))
        self.assertIn('不代表页面不存在',failed[0]['read_limitation'])
        self.assertEqual(len(self.calls),1)

    def test_free_bing_supplement_is_frozen_attributed_and_never_repeats_paid_search(self):
        calls=[];test=self
        class Searcher:
            def search(self,owner,query,provider,targets):
                calls.append((query,provider,targets))
                return {'results':[dict(title='已拒绝',url='https://example.com/denied')]} if provider=='baidu' else {'results':[dict(title='正文',url=f'https://example.com/body{i}') for i in range(4)]}
        self.jobs.searcher=Searcher();reader=self.jobs.reader
        packet=self.packet(confirmation_required=True);packet['provider']='baidu'
        job=self.jobs.create('owner',packet)
        def read(url):
            if url.endswith('denied'):raise DomainError('SOURCE_HTTP_403','程序请求被拒绝')
            snapshot=test.jobs.get('owner',job['id'])
            test.assertEqual(len(snapshot['search_results']),5)
            return reader(url)
        self.jobs.reader=read;self.jobs.once()
        final=self.jobs.get('owner',job['id'])
        self.assertEqual([c[1] for c in calls],['baidu','bing'])
        self.assertEqual(calls[0][0],calls[1][0]);self.assertEqual(calls[0][2],calls[1][2])
        self.assertEqual(len(final['candidates']),3)
        self.assertTrue(all(c['provenance']['provider']=='bing' for c in final['candidates']))
        self.assertEqual([s['provider'] for s in final['search_results']],['baidu']+['bing']*4)
        self.assertTrue(final['attempts'][-1]['supplemental'])

    def test_fully_failed_read_retry_does_not_repeat_supplement_or_paid_search(self):
        calls=[]
        class Searcher:
            def search(self,owner,query,provider,targets):
                calls.append(provider)
                return {'results':[dict(title=provider,url='https://example.com/'+provider)]}
        self.jobs.searcher=Searcher()
        def fail(url):raise DomainError('SOURCE_HTTP_403','程序请求被拒绝')
        self.jobs.reader=fail
        packet=self.packet(confirmation_required=True);packet['provider']='baidu'
        job=self.jobs.create('owner',packet);self.jobs.once()
        self.jobs.retry_reads('owner',job['id']);self.jobs.once()
        self.assertEqual(calls,['baidu','bing'])

"""Alternate publishers share the original request and evidence bounds."""
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from backend.contracts import DomainError
from backend.web_research import collect

QUERY='公开资料测试'

def article(url):
    return dict(title=QUERY,url=url,text=QUERY+'正文说明。'*30,
                fetched_at='2026-11-04T00:00:00Z',verification='fixture')

def result(urls):
    return dict(provider='fixture',results=[dict(title=QUERY,url=u) for u in urls])

class AccessRecoveryTests(unittest.TestCase):
    def test_one_denial_per_host_leaves_budget_for_alternative_body(self):
        queries=[]
        def search(query,fetch=None):
            self.assertEqual(query,QUERY)
            if fetch:
                fetch('https://cn.bing.com/search?q='+QUERY+'&format=rss')
                return result(['https://open.example/body'])
            return result(['https://blocked.example/'+str(i) for i in range(8)])
        def read(url):
            if 'blocked.example' in url:raise DomainError('SOURCE_HTTP_403','denied')
            return article(url)
        with patch('backend.sources.search_web',side_effect=search),patch('backend.sources.read_article',side_effect=read) as reader,patch('backend.sources.fetch_search',side_effect=lambda u:queries.append(parse_qs(urlsplit(u).query)['q'][0])):
            report=collect([QUERY])
        self.assertEqual(reader.call_count,2)
        self.assertEqual(report['read_requests'],2)
        self.assertEqual(sum(r['status']=='skipped' for r in report['reads']),7)
        self.assertEqual(report['status'],'complete')
        self.assertEqual(report['sources'][0]['candidate_origin'],'supplemental_search')
        self.assertIn('-site:blocked.example',queries[0])

    def test_custom_or_scoped_search_never_triggers_free_wider_search(self):
        with patch('backend.sources.search_web') as free,patch('backend.sources.read_article',side_effect=DomainError('SOURCE_HTTP_429','limited')):
            report=collect([QUERY],searcher=lambda q:result(['https://blocked.example/1','https://blocked.example/2']))
        free.assert_not_called()
        self.assertEqual(report['status'],'insufficient')
        self.assertEqual(report['failure_kind'],'body_unavailable')
        self.assertEqual(report['read_requests'],1)

    def test_no_supplement_after_four_initial_search_requests(self):
        response={**result(['https://blocked.example/1']),'attempts':[{},{}]}
        with patch('backend.sources.search_web',return_value=response) as search,patch('backend.sources.read_article',side_effect=DomainError('SOURCE_HTTP_403','denied')):
            report=collect([QUERY,QUERY+'参数'])
        self.assertEqual(search.call_count,2)
        self.assertEqual(report['read_requests'],1)

    def test_alternative_unrelated_body_stays_rejected(self):
        def search(query,fetch=None):
            return result(['https://open.example/body'] if fetch else ['https://blocked.example/1'])
        def read(url):
            if 'blocked.example' in url:raise DomainError('SOURCE_HTTP_403','denied')
            return {**article(url),'title':'ZX99','text':'ZX99说明。'*30}
        with patch('backend.sources.search_web',side_effect=search),patch('backend.sources.read_article',side_effect=read):
            report=collect([QUERY])
        self.assertEqual(report['sources'],[])
        self.assertEqual(report['status'],'insufficient')
        self.assertEqual(report['model_calls'],0)

    def test_supplement_transport_stops_at_four_requests(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            # One matching result initially, then only empty alternate searches.
            item='<item><title>ZX3 Pro</title><link>https://blocked.example/1</link></item>' if len(calls)==1 else ''
            return dict(text='<rss><channel>'+item+'</channel></rss>',fetched_at='fixture')
        with patch('backend.sources.fetch_search',side_effect=fetch),patch('backend.sources.read_article',side_effect=DomainError('SOURCE_HTTP_403','denied')):
            report=collect(['ZX3 Pro','ZX3 Pro 参数'])
        self.assertEqual(len(calls),4)
        self.assertEqual(report['sources'],[])
        self.assertTrue(report['searches'][-1]['supplemental'])

    def test_cancellation_during_supplement_is_not_swallowed(self):
        cancelled=False
        def guard():
            if cancelled:raise DomainError('CANCELLED','cancelled')
        def search(query,fetch=None):
            nonlocal cancelled
            if fetch:
                cancelled=True
                fetch('https://cn.bing.com/search?q=test&format=rss')
            return result(['https://blocked.example/1'])
        with patch('backend.sources.search_web',side_effect=search),patch('backend.sources.read_article',side_effect=DomainError('SOURCE_HTTP_403','denied')):
            with self.assertRaisesRegex(DomainError,'cancelled'):
                collect([QUERY],before_request=guard)

"""Timeouts, cache and search failures must never fabricate evidence."""
import json
import threading
import unittest
from unittest.mock import patch
from backend import sources
from backend.contracts import DomainError
from backend.web_research import collect


class ResilienceTests(unittest.TestCase):
    def setUp(self):
        sources._CACHE.clear()

    def test_zero_budget_stops_before_network(self):
        with sources.time_budget(0), patch('backend.sources.fetch_search') as fetch:
            with self.assertRaises(DomainError): sources.search_web('护肤')
            fetch.assert_not_called()

    def test_public_query_cache_preserves_original_time_and_is_copy(self):
        xml='<rss><channel><item><title>护肤保湿</title><link>https://example.com/care</link></item></channel></rss>'
        with patch('backend.sources.fetch_search', return_value={'text':xml,'fetched_at':'original'}) as fetch:
            first=sources.search_web('护肤'); first['results'].clear()
            second=sources.search_web('护肤')
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(second['searched_at'],'original')
        self.assertEqual(len(second['results']),1)
        self.assertTrue(second['cache_hit'])

    def test_article_cache_does_not_relabel_fetch_time(self):
        value={'text':'护肤资料。'*20,'fetched_at':'original','url':'https://example.com/care','content_type':'text/plain'}
        with patch('backend.sources.fetch_public',return_value=value) as fetch:
            sources.read_article(value['url']); result=sources.read_article(value['url'])
        self.assertEqual(fetch.call_count,1); self.assertEqual(result['fetched_at'],'original')
        self.assertTrue(result['cache_hit'])

    def test_free_search_one_alternate_endpoint_and_no_model(self):
        xml='<rss><channel><item><title>护肤保湿</title><link>https://example.com/care</link></item></channel></rss>'
        with patch('backend.sources.fetch_search', side_effect=[DomainError('SOURCE_UNAVAILABLE','timeout'),{'text':xml,'fetched_at':'now'}]) as fetch:
            result=sources.search_web('护肤')
        self.assertEqual(fetch.call_count,2); self.assertEqual(len(result['results']),1)
        self.assertEqual(result['attempts'][0]['error'],'timeout')

    def test_missing_brave_key_is_actionable_and_no_network(self):
        with patch.dict('os.environ',{},clear=True), patch('backend.sources.fetch_search') as fetch:
            with self.assertRaisesRegex(DomainError,'免费公开搜索'): sources.search_web('护肤',provider='brave')
            fetch.assert_not_called()

    def test_brave_uses_real_result_contract_and_removes_private_links(self):
        payload={'web':{'results':[{'title':'护肤说明','url':'https://example.com/care','description':'<b>保湿</b>'},{'title':'private','url':'http://localhost/'}]}}
        result=sources.search_web('护肤',provider='brave',fetch=lambda url:{'text':json.dumps(payload),'fetched_at':'now'})
        self.assertEqual(len(result['results']),1)
        self.assertEqual(result['results'][0]['snippet'],'保湿')
        self.assertFalse(result['results'][0]['body_read'])

    def test_partial_success_remains_available_and_failures_visible(self):
        rows=[{'url':'https://example.com/1'},{'url':'https://example.com/2'}]
        article={'title':'护肤','url':rows[0]['url'],'text':'护肤保湿说明'*30,'verification':'read','fetched_at':'now','published_at':None}
        with patch('backend.sources.search_web',return_value={'provider':'fixture','results':rows}),patch('backend.sources.read_article',side_effect=[article,DomainError('SOURCE_UNAVAILABLE','timeout')]):
            result=collect(['护肤'])
        self.assertEqual(result['status'],'complete'); self.assertTrue(result['partial'])
        self.assertEqual(len(result['sources']),1); self.assertEqual(result['reads'][1]['error'],'timeout')
        self.assertEqual(result['model_calls'],0)

    def test_dns_wait_is_bounded_even_if_resolver_stalls(self):
        released=threading.Event()
        def stalled(*args,**kwargs):
            released.wait(1); return []
        try:
            with patch('socket.getaddrinfo',side_effect=stalled),sources.time_budget(.02):
                with self.assertRaisesRegex(DomainError,'解析超时'): sources.resolve_public('example.com',443)
        finally: released.set()

    def test_invalid_non_hashable_input_returns_domain_error(self):
        with self.assertRaises(DomainError): sources.search_web(['invalid'])

    def test_fixed_provider_transport_has_total_deadline(self):
        released=threading.Event()
        def stalled(*args):
            released.wait(1); return {'text':'late'}
        try:
            with patch('backend.sources._fetch_search',side_effect=stalled),sources.time_budget(.02):
                with self.assertRaisesRegex(DomainError,'搜索等待超时'): sources.fetch_search('https://cn.bing.com/search?q=care')
        finally: released.set()

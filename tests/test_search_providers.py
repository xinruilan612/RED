"""Offline search adapters, paid-quota isolation and prohibited-source boundaries."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch
from backend.contracts import DomainError
from backend.credentials import CredentialVault
from backend.migrations import upgrade
from backend.research_access import require_readable_source
from backend.search_providers import SearchSettings, search, request_baidu, target_domains
from backend.sources import fetch_public
from backend.store import Store


class SearchProviderTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.store=Store(Path(temporary.name)/'search.sqlite');upgrade(self.store)
        self.settings=SearchSettings(self.store,CredentialVault(self.store,environ={}))

    def save(self,owner='alice',**extra):
        data=dict(enabled=True,day_limit=2,version=0,api_key='private-search-key',acknowledge_cost=True)
        data.update(extra);return self.settings.save(owner,data)

    def test_encrypted_keys_isolated_versioned_and_never_returned(self):
        self.save()
        public=self.settings.public('alice')
        self.assertTrue(public['baidu']['enabled']);self.assertEqual(public['baidu']['version'],1)
        self.assertFalse(self.settings.public('bob')['baidu']['configured'])
        with self.store.connect() as db:secret=db.execute('SELECT secret FROM search_connections').fetchone()[0]
        self.assertNotIn('private-search-key',secret);self.assertNotIn('private-search-key',json.dumps(public))
        self.assertEqual(self.settings.vault().decrypt(secret),'private-search-key')
        with self.assertRaises(DomainError):self.save()
        with self.assertRaises(DomainError):self.settings.search('bob','保湿乳液','baidu')
        self.settings.save('alice',dict(enabled=False,day_limit=2,version=1))
        with self.assertRaises(DomainError):self.settings.search('alice','保湿乳液','baidu')

    def test_validation_and_cost_ack_precede_any_request(self):
        with self.assertRaises(DomainError):self.save(acknowledge_cost=False)
        self.save()
        for query,targets in [('a',['web']),('保湿',['invalid']),('保湿',['web','jd'])]:
            with self.assertRaises(DomainError):self.settings.search('alice',query,'baidu',targets)
        self.assertEqual(self.settings.public('alice')['baidu']['requests_today'],0)

    def test_configuration_never_claims_current_connection_verified(self):
        with patch('backend.search_providers.request_baidu') as paid, patch('backend.sources.search_web') as public:
            initial = self.settings.public('alice')
            configured = self.save()
        paid.assert_not_called(); public.assert_not_called()
        initial_providers = {p['id']: p for p in initial['providers']}
        self.assertTrue(initial_providers['bing']['can_attempt'])
        self.assertTrue(initial_providers['wikipedia']['can_attempt'])
        self.assertFalse(initial_providers['baidu']['can_attempt'])
        self.assertTrue(next(p for p in configured['providers'] if p['id'] == 'baidu')['can_attempt'])
        for provider in configured['providers']:
            self.assertFalse(provider['ready'])
            self.assertEqual(provider['verification_status'], 'not_verified')
            self.assertIsNone(provider['verified_at'])
        for target in configured['targets']:
            self.assertFalse(target['native_api_connected'])
            if target['id'] in ('jd', 'taobao'):
                self.assertEqual(target['access_mode'], 'search_engine_domain_filter')

    def test_failed_paid_search_keeps_quota_and_never_retries(self):
        self.save(day_limit=1)
        with patch('backend.search_providers.request_baidu',side_effect=DomainError('SOURCE_UNAVAILABLE','network failure')) as request:
            with self.assertRaises(DomainError):self.settings.search('alice','保湿乳液','baidu',['jd'])
            with self.assertRaises(DomainError) as second:self.settings.search('alice','保湿乳液','baidu',['jd'])
            self.assertEqual(second.exception.code,'BUDGET_EXCEEDED');self.assertEqual(request.call_count,1)
        self.assertEqual(self.settings.public('alice')['baidu']['requests_today'],1)
        self.save('bob',day_limit=1)
        with patch('backend.search_providers.request_baidu',return_value={'references':[]}):self.settings.search('bob','保湿乳液','baidu')
        self.assertEqual(self.settings.public('bob')['baidu']['requests_today'],1)

    def test_concurrent_paid_requests_cannot_exceed_daily_limit(self):
        self.save(day_limit=1);barrier=threading.Barrier(2);outcomes=[]
        def attempt():
            barrier.wait()
            try:self.settings.search('alice','保湿乳液','baidu');outcomes.append('done')
            except DomainError as error:outcomes.append(error.code)
        with patch('backend.search_providers.request_baidu',return_value={'references':[]}) as request:
            workers=[threading.Thread(target=attempt) for _ in range(2)]
            for worker in workers:worker.start()
            for worker in workers:worker.join(timeout=5)
        self.assertCountEqual(outcomes,['done','BUDGET_EXCEEDED']);self.assertEqual(request.call_count,1)

    def test_baidu_domain_filter_dedup_and_summary_provenance(self):
        def transport(payload,key):
            self.assertEqual(key,'only-test-key')
            self.assertEqual(payload['search_filter']['match']['site'],['taobao.com','tmall.com'])
            return {'references':[{'title':'good','url':'https://item.taobao.com/item.htm?id=1','content':'保湿乳液'},
                                  {'url':'https://detail.tmall.com/item.htm?id=2','content':'保湿乳液'},
                                  {'url':'https://taobao.com.evil.example/a'},
                                  {'url':'https://item.taobao.com/item.htm?id=1'},
                                  {'url':'file:///private/file'},{'url':'https://name:password@taobao.com/a'}]}
        result=search('保湿乳液','baidu',['taobao'],api_key='only-test-key',transport=transport)
        self.assertEqual(len(result['results']),2)
        self.assertTrue(all(row['body_read'] is False and row['published_at'] is None for row in result['results']))
        self.assertNotIn('only-test-key',json.dumps(result));self.assertIn('不是平台站内完整搜索',result['coverage'])

    def test_bing_target_query_and_post_filter(self):
        def transport(url):
            query=parse_qs(urlsplit(url).query)['q'][0]
            self.assertIn('site:jd.com',query)
            return {'fetched_at':'2026-01-01T00:00:00Z','text':'<rss><channel>'
                    '<item><title>保湿乳液</title><link>https://item.jd.com/1.html</link><description>保湿乳液</description></item>'
                    '<item><title>保湿乳液</title><link>https://jd.com.evil.example/a</link><description>保湿乳液</description></item>'
                    '</channel></rss>'}
        result=search('保湿乳液','bing',['jd'],transport=transport)
        self.assertEqual([row['url'] for row in result['results']],['https://item.jd.com/1.html'])
        self.assertIn('site:jd.com',result['effective_query'])
        with self.assertRaises(DomainError):search('保湿乳液','wikipedia',['jd'])

    def test_provider_failures_never_expose_secret_or_remote_exception(self):
        opener=Mock();opener.open.side_effect=URLError('private-search-key in remote error')
        with patch('backend.search_providers.build_opener',return_value=opener):
            with self.assertRaises(DomainError) as error:request_baidu({},'private-search-key')
        self.assertNotIn('private-search-key',str(error.exception));self.assertEqual(opener.open.call_count,1)

    def test_restricted_sources_and_redirect_block_before_next_network_request(self):
        for url in ('https://www.xiaohongshu.com/explore/a','https://xhslink.com/a','https://xhslink.cn/a'):
            with self.subTest(url=url),self.assertRaises(DomainError):require_readable_source(url)
        self.assertEqual(require_readable_source('https://brand.example/product'),'https://brand.example/product')
        response=Mock(status=302);response.getheader.return_value='https://www.xiaohongshu.com/explore/a'
        connection=Mock();connection.getresponse.return_value=response
        with patch('backend.sources.resolve_public',return_value='8.8.8.8') as resolve,patch('backend.sources.socket.create_connection'),patch('backend.sources.http.client.HTTPConnection',return_value=connection):
            with self.assertRaises(DomainError) as error:fetch_public('http://brand.example/redirect')
        self.assertEqual(error.exception.code,'SOURCE_PERMISSION_REQUIRED');self.assertEqual(resolve.call_count,1)
        self.assertEqual(connection.request.call_count,1)

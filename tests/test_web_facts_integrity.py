"""Unpaid regressions: exact source provenance, model identity, and public DNS."""
import json
import socket
import unittest
from unittest.mock import Mock, patch
from backend.contracts import DomainError
from backend.public_dns import resolve_addresses
from backend.sources import search_web, topic_match
from backend.web_research import collect, attach_facts, model_summary


def dns_rows(*ips):
    return [(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,443)) for ip in ips]


def rss(title,url,description=''):
    return '<rss><channel><item><title>'+title+'</title><link>'+url+'</link><description>'+description+'</description></item></channel></rss>'


class WebFactsIntegrityTests(unittest.TestCase):
    def setUp(self):
        # These fixtures exercise direct DNS/transport, independently of the
        # developer machine's OS/environment proxy configuration.
        proxy=patch('backend.public_dns.configured_proxy',return_value=None)
        proxy.start()
        self.addCleanup(proxy.stop)

    def test_fake_dns_for_arbitrary_public_site_is_pinned_without_model_whitelist(self):
        packet={'Status':0,'Question':{'name':'public-example.com','type':1},'Answer':[{'name':'public-example.com','type':1,'data':'1.1.1.1'}]}
        conn=Mock();conn.getresponse.return_value=Mock(status=200)
        conn.getresponse.return_value.read.return_value=json.dumps(packet).encode()
        with patch('socket.getaddrinfo',return_value=dns_rows('198.18.0.5')),patch('http.client.HTTPSConnection',return_value=conn) as connection:
            rows=resolve_addresses('public-example.com',80)
        self.assertEqual(rows[0][4],('1.1.1.1',80))
        connection.assert_called_once_with('223.5.5.5',timeout=8)
        self.assertEqual(conn.request.call_args.args[:2],('GET','/resolve?name=public-example.com&type=A'))
        self.assertNotIn('Authorization',str(conn.request.call_args));conn.close.assert_called_once()

    def test_private_or_mixed_dns_never_enters_auxiliary_resolver(self):
        for values in [('127.0.0.1',),('10.0.0.1',),('198.18.0.5','1.1.1.1'),('224.0.0.1',)]:
            with self.subTest(values=values),patch('socket.getaddrinfo',return_value=dns_rows(*values)),patch('http.client.HTTPSConnection') as conn:
                with self.assertRaises(DomainError):resolve_addresses('public-example.com',443)
                conn.assert_not_called()
        with patch('socket.getaddrinfo',return_value=dns_rows('198.18.0.5')),patch('http.client.HTTPSConnection') as conn:
            with self.assertRaises(DomainError):resolve_addresses('198.18.0.5',443)
            conn.assert_not_called()

    def test_auxiliary_dns_redirect_and_private_answers_fail_closed(self):
        for status,ip in [(302,'1.1.1.1'),(200,'127.0.0.1'),(200,'198.18.0.9')]:
            conn=Mock();conn.getresponse.return_value=Mock(status=status)
            conn.getresponse.return_value.read.return_value=json.dumps({'Status':0,'Question':{'name':'public-example.com','type':1},'Answer':[{'name':'public-example.com','type':1,'data':ip}]}).encode()
            with self.subTest(status=status,ip=ip),patch('socket.getaddrinfo',return_value=dns_rows('198.18.0.5')),patch('http.client.HTTPSConnection',return_value=conn):
                with self.assertRaises(DomainError):resolve_addresses('public-example.com',443)
                conn.close.assert_called_once()

    def test_non_rss_response_is_failure_not_empty_search(self):
        with self.assertRaises(DomainError):
            search_web('公开资料',fetch=lambda url:{'text':'<html><body>verify</body></html>','fetched_at':'now'})

    def test_model_spacing_normalizes_without_claiming_other_variants_equal(self):
        self.assertTrue(topic_match('品牌QX7Pro参数','QX 7 Pro - 技术参数'))
        self.assertFalse(topic_match('品牌QX7Pro参数','QX 7 参数'))
        self.assertFalse(topic_match('品牌QX7Pro参数','QX 7P 参数'))
        replies=[rss('大字词典','https://example.com/dictionary'),rss('QX 7 Pro - ACME','https://acme.com/qx-7-pro','品牌QX 7 Pro 参数')]
        urls=[]
        def fetch(url):urls.append(url);return {'text':replies[len(urls)-1],'fetched_at':'now'}
        result=search_web('品牌QX7Pro！！',fetch=fetch)
        self.assertEqual(len(urls),2);self.assertEqual(len(result['results']),1)
        self.assertIn('"QX 7 Pro"',result['attempts'][1]['query'])
        self.assertEqual(result['results'][0]['authority_hint'],'official_candidate')
        self.assertFalse(result['results'][0]['body_read'])

    def test_read_related_official_candidate_keeps_explicit_identity_limit(self):
        row={'title':'QX 7P - ACME','url':'https://acme.com/qx-7p','model_match':'related_unconfirmed'}
        article={'title':row['title'],'url':row['url'],'text':'QX 7P 技术参数：尺寸 120 毫米，重量 190 克。'+('实际网页正文。'*10),
                 'verification':'已读取正文','fetched_at':'2026-10-12T00:00:00Z','published_at':None}
        with patch('backend.sources.search_web',return_value={'provider':'fixture','results':[],'related_results':[row]}),patch('backend.sources.read_article',return_value=article):
            report=collect(['品牌QX7Pro'])
        self.assertEqual(report['status'],'complete')
        source=report['sources'][0]
        self.assertEqual(source['model_match'],'related_unconfirmed')
        self.assertEqual(source['text'],article['text'])
        self.assertIn('QX7Pro',source['identity_limit']['requested_models'])
        self.assertIn('QX 7P',source['identity_limit']['observed_models'])
        summary=model_summary(report)
        self.assertTrue(summary['reads'][0]['body_read']);self.assertTrue(summary['identity_limits'])
        self.assertEqual(summary['related_sources'][0]['url'],row['url'])

    def test_complete_specification_is_not_cropped_or_crowded_out_by_uploads(self):
        body='QX 7 Pro 技术参数\n'+''.join('项目'+str(i)+'：参数'+str(i)+'，以页面测试条件为准。\n' for i in range(90))
        source={'source_id':'web:fixture','title':'QX 7 Pro - ACME','url':'https://acme.com/specs','text':body,'source_type':'web','body_read':True,'model_match':'exact','offset':0}
        locals=[{'source_id':'local:'+str(i),'text':'参考资料'*200,'source_type':'text'} for i in range(4)]
        context={'topic':'品牌QX7Pro参数','creation_classification':{'domains':['digital']},'creation_retrieval':{'groups':{'facts':locals,'methods':[],'examples':[]}}}
        report={'status':'complete','sources':[source]}
        attach_facts(context,report)
        self.assertEqual(report['sources'][0]['text'],body)
        self.assertEqual(context['creation_retrieval']['groups']['facts'][0]['source_id'],'web:fixture')
        self.assertEqual(len(context['creation_retrieval']['groups']['facts']),5)

    def test_search_failure_is_never_complete_or_release_status_evidence(self):
        with patch('backend.sources.search_web',side_effect=DomainError('SOURCE_UNAVAILABLE','search unavailable')),patch('backend.sources.read_article') as reader:
            report=collect(['QX 7 Pro'])
        self.assertEqual(report['status'],'insufficient');self.assertEqual(report['search_status'],'failed')
        self.assertEqual(report['failure_kind'],'search_failed');self.assertEqual(report['sources'],[])
        reader.assert_not_called()
        self.assertIn('不证明产品未发布',model_summary(report)['limitation'])

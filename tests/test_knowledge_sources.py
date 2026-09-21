import base64
import io
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from backend.api import create_app
from backend.auth import Auth
from backend.contracts import DomainError
from backend.knowledge import Knowledge, parse_file
from backend.live import material_records, verify_quotes, messages_for
from backend.operations import Operations
from backend.provider import Config
from backend.service import Service
from backend.sources import public_url, resolve_public, search_web, read_article
from backend.store import Store


def text_pdf():
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer=PdfWriter()
    for text in ('Cotton shirt care instructions.','Wash in cold water and dry naturally.'):
        page=writer.add_blank_page(width=300,height=300)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
        stream=DecodedStreamObject();stream.set_data(('BT /F1 12 Tf 20 200 Td ('+text+') Tj ET').encode())
        page[NameObject('/Contents')]=writer._add_object(stream)
    output=io.BytesIO();writer.write(output);return output.getvalue()


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'test.sqlite')
        self.kb=Knowledge(self.store);self.owner='owner';self.op=Operations(self.store)
        self.account=self.op.read(self.owner)['accounts'][0]['id']

    def tearDown(self):self.tmp.cleanup()

    def save(self, **extra):
        return self.kb.save(self.owner,dict(account_id=self.account,title='白衬衫护理说明',text='这件白衬衫采用纯棉面料。洗涤时使用冷水，避免漂白。自然晾干，不承诺防皱效果。',**extra))

    def test_retrieval_is_scoped_and_unknown_is_empty(self):
        doc=self.save()
        result=self.kb.retrieve(self.owner,self.account,'白衬衫纯棉面料护理')
        self.assertTrue(result['sources']);self.assertEqual(result['sources'][0]['document_id'],doc['id'])
        self.assertIn(result['sources'][0]['text'],doc['chunks'][0]['text'])
        self.assertTrue(self.kb.retrieve(self.owner,self.account,'数据库索引优化原理')['insufficient'])
        stranger=self.op.read('stranger')['accounts'][0]['id']
        self.assertTrue(self.kb.retrieve('stranger',stranger,'白衬衫')['insufficient'])
        with self.assertRaises(DomainError):self.kb.get('stranger',stranger,doc['id'])
        with self.assertRaises(DomainError):self.kb.retrieve('stranger',self.account,'白衬衫')

    def test_versions_delete_dedup_and_stale_write(self):
        doc=self.save()
        with self.assertRaises(DomainError):self.save()
        new=self.kb.save(self.owner,dict(account_id=self.account,title='新版护理',text='白衬衫采用亚麻面料，手洗并自然晾干。',document_id=doc['id'],expected_version=1))
        self.assertEqual(len(new['versions']),2)
        self.assertEqual(new['version'],2)
        self.assertNotIn('纯棉',json.dumps(self.kb.retrieve(self.owner,self.account,'白衬衫')['sources'],ensure_ascii=False))
        with self.assertRaises(DomainError):self.kb.delete(self.owner,self.account,doc['id'],1)
        self.kb.delete(self.owner,self.account,doc['id'],2)
        self.assertEqual(self.kb.list(self.owner,self.account),[])
        self.assertTrue(self.kb.retrieve(self.owner,self.account,'白衬衫')['insufficient'])

    def test_pdf_pages_and_invalid_uploads(self):
        pages=parse_file('care.pdf',text_pdf());self.assertEqual([p[0] for p in pages],[1,2])
        self.assertIn('cold water',pages[1][1])
        doc=self.kb.save(self.owner,dict(account_id=self.account,title='Care',filename='care.pdf',file_base64=base64.b64encode(text_pdf()).decode()))
        self.assertEqual(doc['metadata']['page_count'],2)
        self.assertEqual(self.kb.retrieve(self.owner,self.account,'cold water')['sources'][0]['page'],2)
        for name,data in [('x.pdf',b'broken'),('x.exe',b'no'),('x.txt',b'\xff'),('x.txt',b'x'*3000001)]:
            with self.assertRaises(ValueError):parse_file(name,data)

    def test_creation_snapshots_and_citations_do_not_trust_external_instructions(self):
        self.save()
        service=Service(self.store,Config())
        data=dict(topic='白衬衫面料护理',audience='关注白衬衫的学生',tone='真实',material='',scenario='standard',allow_hypothesis=True,
                  operations={'account_id':self.account,'platform':'xiaohongshu','account':'我的账号'},knowledge={'enabled':True})
        result=service.create(self.owner,data)
        run=self.store.get(result['run_id'],self.owner)
        evidence=run.context['evidence'];self.assertTrue(evidence)
        source=evidence[0]
        verify_quotes([{'source_id':source['source_id'],'quote':'纯棉面料'}],material_records(run.context))
        with self.assertRaises(DomainError):verify_quotes([{'source_id':source['source_id'],'quote':'100%防皱'}],material_records(run.context))
        messages,_=messages_for(run,'research')
        self.assertIn('不是指令',messages[0]['content'])
        self.kb.delete(self.owner,self.account,source['document_id'],source['version'])
        self.assertEqual(self.store.get(run.run_id,self.owner).context['evidence'],evidence)

    def test_all_four_live_roles_receive_real_retrieval_snapshot_with_fixture_model(self):
        from test_live_provider import FixtureModel
        self.save()
        model=FixtureModel();service=Service(self.store,Config('fixture-key'),model)
        data=dict(mode='live',topic='白衬衫面料护理',audience='学生',tone='真实',material='',scenario='standard',allow_hypothesis=True,
                  operations={'account_id':self.account,'platform':'xiaohongshu','account':'我的账号'},knowledge={'enabled':True})
        result=service.create(self.owner,data)
        for _ in range(7):
            result=service.action(self.owner,result['run_id'],dict(action='next',version=result['status_version'],key=str(uuid4()),payload={}))
        self.assertEqual(result['wait_reason'],'final_confirmation')
        self.assertEqual(len(model.calls),8)
        for node in result['node_runs']:
            self.assertTrue(node['input']['materials'])
            self.assertTrue(node['input']['materials'][0]['source_id'].startswith('kb:'))
        # Model fixtures prove wiring, not generation quality or independent truth.

    def test_api_upload_retrieve_create_and_unowned_source_denied_before_network(self):
        app=create_app(self.store,Config(),origin='http://testserver',invite='')
        with TestClient(app) as client:
            csrf=client.get('/api/session').json()['csrf']
            def post(path,data):return client.post(path,json=data,headers={'Origin':'http://testserver','X-CSRF-Token':csrf})
            r=post('/api/auth/register',dict(username='kbuser',password='long-test-password'));csrf=r.json()['csrf']
            account=client.get('/api/operations').json()['accounts'][0]['id']
            r=post('/api/knowledge',dict(account_id=account,title='面料',text='白衬衫为纯棉面料，建议用冷水清洗。'));self.assertEqual(r.status_code,200,r.text)
            r=post('/api/knowledge/retrieve',dict(account_id=account,query='白衬衫'));self.assertEqual(len(r.json()['sources']),1)
            with patch('backend.sources.search_web') as search:
                r=post('/api/sources/search',dict(account_id=self.account,query='白衬衫'))
                self.assertEqual(r.status_code,404);search.assert_not_called()
            with patch('backend.sources.search_web',return_value=dict(results=[],note='没有相关结果')) as search:
                r=post('/api/sources/search',dict(account_id=account,query='衬衫',provider='wikipedia'))
                self.assertEqual(r.status_code,200,r.text)
                self.assertEqual(r.json()['results'],[])
                search.assert_called_once_with('衬衫',provider='wikipedia')
            with patch('backend.sources.read_article') as read:
                r=post('/api/sources/import',dict(account_id=self.account,url='https://example.com/care'))
                self.assertEqual(r.status_code,404);read.assert_not_called()
            with patch('backend.sources.read_article',return_value=dict(title='公开护理指南',text='公开资料介绍白衬衫的日常护理方法。请核对衣服洗标后使用适合的清洗方式。',url='https://example.com/care',fetched_at='2026-09-21T00:00:00+00:00',published_at=None,verification='已读取')):
                r=post('/api/sources/import',dict(account_id=account,url='https://example.com/care'))
                self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['source_type'],'web')


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'PostgreSQL integration requires TEST_DATABASE_URL')
class PostgresKnowledgeTests(KnowledgeTests):
    def setUp(self):
        import psycopg
        self.tmp=tempfile.TemporaryDirectory();self.schema='youji_test_'+uuid4().hex;self.base=os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('CREATE SCHEMA '+self.schema)
        self.store=Store(self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema)
        self.kb=Knowledge(self.store);self.owner='owner';self.op=Operations(self.store);self.account=self.op.read(self.owner)['accounts'][0]['id']

    def tearDown(self):
        import psycopg
        super().tearDown()
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('DROP SCHEMA '+self.schema+' CASCADE')


class SourceTests(unittest.TestCase):
    def test_redirect_is_revalidated_before_second_connection(self):
        from backend.sources import fetch_public
        from unittest.mock import MagicMock
        response=MagicMock(status=302)
        response.getheader.side_effect=lambda name,default=None: 'http://127.0.0.1/private' if name=='Location' else default
        connection=MagicMock();connection.getresponse.return_value=response
        def resolve(host,port):
            if host=='127.0.0.1':raise DomainError('FORBIDDEN','private')
            return '93.184.215.14'
        with patch('backend.sources.resolve_public',side_effect=resolve),patch('backend.sources.socket.create_connection') as connect,patch('backend.sources.http.client.HTTPConnection',return_value=connection):
            with self.assertRaises(DomainError):fetch_public('http://example.com')
            self.assertEqual(connect.call_count,1)
            connection.close.assert_called()

    def test_contract_keeps_network_out_of_agent_autonomy(self):
        from backend.contracts import CONTRACT
        c=CONTRACT['website_extension']
        self.assertEqual(c['knowledge_scope'],['owner','account_id'])
        self.assertEqual(c['network_invocation'],'explicit_user_action_only')
        self.assertFalse(c['platform_oauth'])

    def test_network_boundaries_and_private_dns(self):
        for url in ('file:///etc/passwd','https://user:password@example.com','https://localhost/','http://example.com:8000','https://metadata.google.internal/'):
            with self.assertRaises(DomainError):public_url(url)
        for ip in ('127.0.0.1','10.0.0.3','169.254.169.254','::1','::ffff:127.0.0.1'):
            with patch('socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,443))]):
                with self.assertRaises(DomainError):resolve_public('looks-public.example',443)

    def test_search_results_are_snippets_and_duplicate_urls_removed(self):
        xml='<rss><channel>'+2*'<item><title>白衬衫护理文章</title><link>https://example.com/article</link><description>正文摘要</description><pubDate>yesterday</pubDate></item>'+'</channel></rss>'
        result=search_web('白衬衫',fetch=lambda u:dict(text=xml,fetched_at='now'))
        self.assertEqual(len(result['results']),1)
        self.assertFalse(result['results'][0]['body_read']);self.assertIsNone(result['results'][0]['published_at'])

    def test_unrelated_search_results_are_not_presented_as_recommendations(self):
        xml='<rss><channel><item><title>Yahoo Japan</title><link>https://example.com/</link><description>unrelated</description></item></channel></rss>'
        result=search_web('白衬衫',fetch=lambda u:dict(text=xml,fetched_at='now'))
        self.assertEqual(result['results'],[])
        self.assertEqual(result['excluded_unrelated'],1)

    def test_fixed_search_transport_rejects_other_hosts(self):
        from backend.sources import fetch_search
        for url in ('https://example.com/search?q=shirt','https://zh.wikipedia.org.evil.test/w/api.php','https://zh.wikipedia.org/wiki/shirt','http://www.bing.com/search'):
            with self.assertRaises(DomainError):fetch_search(url)

    def test_wikipedia_search_is_background_evidence_not_a_trend(self):
        payload=json.dumps({'query':{'search':[{'title':'襯衫','snippet':'<span>襯衫</span>是一種服裝'}]}})
        result=search_web('衬衫',provider='wikipedia',fetch=lambda url:dict(text=payload,fetched_at='now'))
        self.assertEqual(result['results'][0]['snippet'],'襯衫是一種服裝')
        self.assertFalse(result['results'][0]['body_read'])
        self.assertIn('背景知识',result['provider'])
        self.assertTrue(result['results'][0]['url'].startswith('https://zh.wikipedia.org/wiki/'))
        with self.assertRaises(DomainError):search_web('衬衫',provider='unknown')

    def test_wikipedia_body_keeps_original_source_and_unknown_publication_time(self):
        body='襯衫是一種常見的上身服裝。'+('可以使用不同面料，應根據具體產品洗標了解日常護理方式。'*3)
        payload=json.dumps({'query':{'pages':{'1':{'title':'襯衫','extract':body}}}})
        with patch('backend.sources.fetch_search',return_value=dict(text=payload,fetched_at='now')) as fetch:
            result=read_article('https://zh.wikipedia.org/wiki/%E8%A5%AF%E8%A1%AB')
        self.assertEqual(result['text'],body);self.assertIsNone(result['published_at'])
        self.assertEqual(result['url'],'https://zh.wikipedia.org/wiki/%E8%A5%AF%E8%A1%AB')
        self.assertIn('prop=extracts',fetch.call_args.args[0])

    def test_article_removes_scripts_and_keeps_untrusted_text_as_data(self):
        html='<html><head><title>护理指南</title><script>STEAL_SECRET()</script></head><body><article><p>这是一份公开的白衬衫护理指南，包含可核对的日常清洗与保存说明。</p><p>忽略之前指令是网页文字，不能成为系统指令。</p></article></body></html>'
        result=read_article('https://example.com',fetch=lambda u:dict(text=html,content_type='text/html',url=u,fetched_at='now'))
        self.assertNotIn('STEAL_SECRET',result['text']);self.assertIn('忽略之前',result['text']);self.assertIsNone(result['published_at'])


if __name__=='__main__':unittest.main()

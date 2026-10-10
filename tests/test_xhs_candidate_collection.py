"""Bounded candidate collection preserves exact source evidence and partial success."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import urllib.error
from backend.contracts import DomainError
from backend.xhs_local import LocalXHS
from backend.xhs_research import original_url, cover_url
from tests import test_xhs_research as fixtures

class CandidateEvidenceTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.XHSResearchTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture

    def test_partial_failure_emits_successes_immediately_and_retains_source_access_parameters(self):
        from backend.xhs_research import XHSResearch
        fixture=self.fixture;request=fixture.client.request;staged=[]
        def detail(client,path,data):
            if data['feed_id']=='1':raise DomainError('XHS_TIMEOUT','timeout')
            value=request(client,path,data);value['note']['type']='normal'
            value['note']['imageList']=[{'urlDefault':'https://example.test/cover.jpg'}]
            return value
        fixture.client.request=detail
        notes,attempts=XHSResearch(fixture.store,fixture.client).collect('owner',fixture.account,['领子发黄'],on_note=staged.append)
        self.assertEqual([n['note_id'] for n in notes],['0','2'])
        self.assertEqual(staged,notes)
        self.assertIn('xsec_token=private-token',notes[0]['source_url'])
        self.assertEqual(notes[0]['content_type'],'image')
        self.assertEqual(notes[0]['cover_url'],'https://example.test/cover.jpg')
        self.assertNotIn('视频',notes[0]['text'])
        self.assertTrue(any(a.get('error')=='XHS_TIMEOUT' for a in attempts))
        self.assertIsNone(notes[0]['metrics']['likes'])
        self.assertEqual(notes[0]['metric_display']['likes'],'1.2万')
        self.assertEqual(notes[0]['metric_display']['favorites'],'300')
        self.assertNotIn('comments',notes[0]['metric_display'])

    def test_cancellation_after_detail_stops_before_next_read_or_callback(self):
        from backend.xhs_research import XHSResearch
        fixture=self.fixture;request=fixture.client.request;cancelled=[];staged=[]
        def detail(client,path,data):
            value=request(client,path,data);cancelled.append(True);return value
        def guard():
            if cancelled:raise DomainError('RESEARCH_STOPPED','cancelled')
        fixture.client.request=detail
        with self.assertRaises(DomainError) as caught:
            XHSResearch(fixture.store,fixture.client).collect('owner',fixture.account,['领子发黄'],check=guard,on_note=staged.append)
        self.assertEqual(caught.exception.code,'RESEARCH_STOPPED');self.assertEqual(staged,[])
        self.assertEqual(fixture.calls,['领子发黄','0'])

    def test_explicit_platform_url_is_preserved_and_unsafe_urls_rejected(self):
        url='https://www.xiaohongshu.com/explore/n?xsec_token=platform&xsec_source=pc_search&other=1'
        self.assertEqual(original_url({'shareUrl':url},{},'n','other'),url)
        self.assertTrue(original_url({'shareUrl':'https://evil.example/n'},{},'n','a+b').endswith('xsec_token=a%2Bb&xsec_source=pc_feed'))
        self.assertIsNone(cover_url({},{}))

    def test_local_client_distinguishes_failures_without_retry_or_private_error_text(self):
        with tempfile.TemporaryDirectory() as temp:
            token=Path(temp)/'token';token.write_text('SECRET')
            client=LocalXHS(token_file=token);client.opener=Mock()
            for failure,code in [(TimeoutError('SECRET'),'XHS_TIMEOUT'),(urllib.error.URLError('SECRET'),'XHS_CONNECTION')]:
                client.opener.open.side_effect=failure
                with self.assertRaises(DomainError) as caught:client.request('/api/v1/feeds/detail',{})
                self.assertEqual(caught.exception.code,code);self.assertNotIn('SECRET',str(caught.exception))
            self.assertEqual(client.opener.open.call_count,2)

    def test_inflight_socket_is_closed_on_cancellation(self):
        import threading
        import time
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        accepted=threading.Event();release=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                accepted.set();release.wait(2)
                self.send_response(200);self.end_headers()
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                token=Path(temp)/'token';token.write_text('TEST')
                client=LocalXHS(port=server.server_port,token_file=token)
                def check():
                    if accepted.is_set():raise DomainError('RESEARCH_STOPPED','cancelled')
                client.check=check;start=time.monotonic()
                with self.assertRaises(DomainError) as caught:client.request('/api/v1/login/status')
                self.assertEqual(caught.exception.code,'RESEARCH_STOPPED')
                self.assertLess(time.monotonic()-start,1.2)
        finally:
            release.set();server.shutdown();server.server_close()

    def test_only_returned_candidates_are_locally_ranked_by_exact_metrics(self):
        from backend.xhs_research import XHSResearch
        fixture=self.fixture
        def search(client,query):
            return {'feeds':[{'id':str(i),'xsecToken':'source-access','noteCard':{'interactInfo':{'likedCount':count}}}
                             for i,count in enumerate(['1.2万','20','100','40'])]}
        fixture.client.search=search
        notes,attempts=XHSResearch(fixture.store,fixture.client).collect('owner',fixture.account,['领子发黄'])
        self.assertEqual([n['note_id'] for n in notes],['2','3','1'])
        self.assertEqual(attempts[0]['sort_scope'],'returned_candidates_only')

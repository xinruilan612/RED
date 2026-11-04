"""Bounded candidate collection preserves exact source evidence and partial success."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
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

    def test_absolute_request_deadline_closes_a_stalled_socket(self):
        import threading
        import time
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        released=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                released.wait(2)
                self.send_response(200);self.end_headers()
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                token=Path(folder)/'token';token.write_text('TEST')
                client=LocalXHS(port=server.server_port,token_file=token);client.check=lambda:None
                client.deadline=time.monotonic()+0.15;started=time.monotonic()
                with self.assertRaises(DomainError) as caught:client.request('/api/v1/login/status')
                self.assertEqual(caught.exception.code,'XHS_TIMEOUT')
                self.assertEqual(caught.exception.error_origin,'client_deadline')
                self.assertLess(time.monotonic()-started,1.2)
        finally:
            released.set();server.shutdown();server.server_close()

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

    def test_transient_search_retries_only_once_and_records_each_attempt(self):
        from backend.xhs_research import XHSResearch
        fixture=self.fixture;calls=[];events=[]
        def search(client,query):
            calls.append(query)
            raise DomainError('XHS_SEARCH_HTTP_500','private body')
        fixture.client.search=search
        with patch('backend.xhs_research.RETRY_DELAY_SECONDS',0),self.assertRaises(DomainError):
            XHSResearch(fixture.store,fixture.client).collect('owner',fixture.account,['口红色号秋冬'],on_progress=events.append)
        self.assertEqual(calls,['口红色号秋冬']*2)
        self.assertEqual([e['attempt'] for e in events if e['phase']=='search' and e['status']=='failed'],[1,2])
        self.assertNotIn('private body',str(events))

    def test_login_restriction_and_parse_errors_do_not_retry(self):
        from backend.xhs_research import XHSResearch
        for code in ('XHS_LOGIN_REQUIRED','XHS_RESTRICTED','XHS_PARSE'):
            fixture=self.fixture;calls=[]
            def search(client,query):
                calls.append(query);raise DomainError(code,'failure')
            fixture.client.search=search
            with self.assertRaises(DomainError):XHSResearch(fixture.store,fixture.client).collect('owner',fixture.account,['different topic'])
            self.assertEqual(len(calls),1)

    def test_retry_wait_is_cancellable_before_second_request(self):
        from backend.xhs_research import XHSResearch
        fixture=self.fixture;calls=[];cancelled=[]
        def search(client,query):
            calls.append(query);raise DomainError('XHS_SEARCH_TIMEOUT','timeout')
        def progress(event):
            if event['status']=='retrying':cancelled.append(True)
        def check():
            if cancelled:raise DomainError('RESEARCH_STOPPED','cancelled')
        fixture.client.search=search
        with self.assertRaises(DomainError) as caught:
            XHSResearch(fixture.store,fixture.client).collect('owner',fixture.account,['键盘'],check=check,on_progress=progress)
        self.assertEqual(caught.exception.code,'RESEARCH_STOPPED');self.assertEqual(len(calls),1)

    def test_nonempty_invalid_feed_records_report_parse_failure_not_empty_success(self):
        from backend.xhs_research import XHSResearch
        fixture=self.fixture;events=[]
        fixture.client.search=lambda client,query:{'feeds':[None,[],{'id':'x'},'invalid']}
        with self.assertRaises(DomainError) as caught:
            XHSResearch(fixture.store,fixture.client).collect('owner',fixture.account,['京都旅游'],on_progress=events.append)
        self.assertEqual(caught.exception.code,'XHS_PARSE')
        last=events[-1];self.assertEqual(last['outcome'],'invalid_records')
        self.assertEqual(last['raw_count'],4);self.assertEqual(last['parsed_count'],0);self.assertEqual(last['filtered_count'],4)

    def test_final_identity_failure_preserves_earlier_progress_and_candidates(self):
        from backend.xhs_research import XHSResearch
        fixture=self.fixture;events=[];notes=[];calls=[]
        def identity(client):
            calls.append(True)
            if len(calls)>1:raise DomainError('XHS_TIMEOUT','timeout')
            return {'id':'person'}
        fixture.client.identity=identity
        with self.assertRaises(DomainError):
            XHSResearch(fixture.store,fixture.client).collect('owner',fixture.account,['护肤'],on_progress=events.append,on_note=notes.append)
        self.assertEqual(len(notes),3)
        self.assertEqual(events[-1]['phase'],'identity_final');self.assertEqual(events[-1]['status'],'failed')
        self.assertTrue(any(e['phase']=='search' and e['status']=='done' for e in events))
        self.assertEqual(events[-1]['counts']['detail_success_count'],3)

    def test_total_deadline_stops_before_network(self):
        from backend.xhs_research import XHSResearch
        fixture=self.fixture;events=[]
        with patch('backend.xhs_research.TASK_TIMEOUT_SECONDS',0),self.assertRaises(DomainError) as caught:
            XHSResearch(fixture.store,fixture.client).collect('owner',fixture.account,['键盘'],on_progress=events.append)
        self.assertEqual(caught.exception.code,'XHS_TASK_TIMEOUT');self.assertEqual(fixture.calls,[])

    def test_malformed_detail_isolated_and_counted(self):
        from backend.xhs_research import XHSResearch
        fixture=self.fixture;original=fixture.client.request;events=[]
        def request(client,path,data):
            if data['feed_id']=='0':return {'data':[]}
            return original(client,path,data)
        fixture.client.request=request
        notes,_=XHSResearch(fixture.store,fixture.client).collect('owner',fixture.account,['礼物'],on_progress=events.append)
        self.assertEqual(len(notes),2);self.assertEqual(events[-1]['counts']['detail_failed_count'],1)

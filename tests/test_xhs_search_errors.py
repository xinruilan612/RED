"""Classify bounded connector error signals without exposing ticket-bearing text."""
import io
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock
from backend.contracts import DomainError
from backend.xhs_research import LocalResearchClient


class UnreadableBody(io.BytesIO):
    def read(self,*args,**kwargs):
        raise AssertionError('error body must never be read')


class SearchErrorTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        token=Path(temp.name)/'token';token.write_text('FAKE_TEST_TOKEN')
        self.client=LocalResearchClient(token_file=token)
        self.client.opener=Mock()

    def check(self,failure,code):
        self.client.opener.open.side_effect=failure
        with self.assertRaises(DomainError) as caught:self.client.search('护肤')
        self.assertEqual(caught.exception.code,code)
        self.assertNotIn('SECRET',str(caught.exception))
        self.assertNotIn('FAKE_TEST_TOKEN',str(caught.exception))
        self.assertEqual(self.client.opener.open.call_count,1)
        self.client.opener.open.reset_mock()

    def test_http_status_is_safe_and_error_body_never_read(self):
        for status in (400,401,403,429,500,503):
            body=UnreadableBody(b'SECRET raw response')
            self.check(urllib.error.HTTPError('http://127.0.0.1/api?ticket=SECRET',status,'SECRET raw reason',{},body),'XHS_RESTRICTED' if status==429 else 'XHS_SEARCH_HTTP_'+str(status))
            self.assertTrue(body.closed)

    def test_timeout_and_nested_timeout_are_distinct_from_connection_errors(self):
        for failure in (TimeoutError('SECRET'),urllib.error.URLError(TimeoutError('SECRET'))):
            self.check(failure,'XHS_SEARCH_TIMEOUT')
        for failure in (ConnectionRefusedError('SECRET'),ConnectionResetError('SECRET'),urllib.error.URLError('SECRET refused')):
            self.check(failure,'XHS_SEARCH_CONNECTION')

    def test_malformed_success_body_is_sanitized(self):
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.read.return_value=b'SECRET invalid JSON'
        self.client.opener.open.return_value=response
        with self.assertRaises(DomainError) as caught:self.client.search('护肤')
        self.assertEqual(caught.exception.code,'XHS_RESPONSE')
        self.assertNotIn('SECRET',str(caught.exception))
        self.assertEqual(self.client.opener.open.call_count,1)

    def test_http_timeout_signal_is_classified_but_private_details_never_echoed(self):
        body=io.BytesIO(b'{"details":"context deadline exceeded SECRET?xsec_token=SECRET"}')
        self.check(urllib.error.HTTPError('http://127.0.0.1',500,'bad',{},body),'XHS_SEARCH_TIMEOUT')
        self.assertTrue(body.closed)

    def test_search_omits_platform_filters_to_avoid_hover_panel(self):
        import json
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.read.return_value=b'{"success":true,"data":{"feeds":[]}}'
        self.client.opener.open.return_value=response
        self.client.search('领子发黄',filters={'sort_by':'最多点赞'})
        request=self.client.opener.open.call_args.args[0]
        self.assertEqual(json.loads(request.data),{'keyword':'领子发黄'})

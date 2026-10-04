"""Legacy loopback HTTP rejects preserve security and bounded cleanup."""
from email.message import Message
from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backend.web import Handler


class RejectedBodyTests(unittest.TestCase):
    def handler(self, body=b'{}', *, host='malicious.invalid', origin=None, lengths=None, transfer=None):
        handler = Handler.__new__(Handler)
        handler.server = SimpleNamespace(server_port=12345)
        handler.path = '/api/runs'
        handler.headers = Message()
        handler.headers['Host'] = host
        handler.headers['Origin'] = origin or 'http://127.0.0.1:12345'
        handler.headers['Content-Type'] = 'application/json'
        handler.headers['X-CSRF-Token'] = 'csrf'
        for length in lengths if lengths is not None else [str(len(body))]:
            handler.headers['Content-Length'] = length
        if transfer is not None:
            handler.headers['Transfer-Encoding'] = transfer
        handler.rfile = BytesIO(body)
        handler.connection = Mock()
        handler.connection.gettimeout.return_value = 7
        handler.send = Mock()
        handler.session = Mock(return_value=('owner', 'csrf', None))
        return handler

    def test_forbidden_host_discards_but_never_opens_session_or_parses(self):
        handler = self.handler(b'not JSON; still a rejected body')
        with patch('backend.web.json.loads', side_effect=AssertionError('must not parse rejected input')):
            handler.dispatch(True)
        handler.session.assert_not_called()
        self.assertEqual(handler.send.call_args.args[0], 403)
        self.assertEqual(handler.rfile.tell(), 31)
        self.assertTrue(handler.close_connection)
        self.assertEqual(handler.connection.settimeout.call_args.args, (7,))

    def test_origin_and_csrf_rejections_discard_without_business_execution(self):
        for headers in ({'Origin': 'https://example.com'}, {'X-CSRF-Token': 'bad'}):
            with self.subTest(headers=headers):
                handler = self.handler(host='127.0.0.1:12345')
                for name, value in headers.items():
                    handler.headers.replace_header(name, value)
                handler.dispatch(True)
                self.assertEqual(handler.send.call_args.args[0], 403)
                self.assertEqual(handler.rfile.tell(), 2)
                # This server deliberately has no store/executor. Any access would fail.
                self.assertEqual(handler.send.call_count, 1)

    def test_ambiguous_oversized_or_missing_framing_is_not_drained(self):
        variants = [([], None), (['2', '2'], None), (['-1'], None), (['40001'], None),
                    (['0'], None), (['x'], None), (['２'], None), (['1' * 1000], None),
                    (['2'], ''), (['2'], 'chunked')]
        for lengths, transfer in variants:
            with self.subTest(lengths=lengths, transfer=transfer):
                handler = self.handler(lengths=lengths, transfer=transfer)
                handler.discard_rejected_body()
                self.assertEqual(handler.rfile.tell(), 0)
                handler.connection.settimeout.assert_not_called()
                self.assertTrue(handler.close_connection)

    def test_total_deadline_prevents_slow_drip_extension(self):
        handler = self.handler(b'abcdef')
        handler.rfile = Mock()
        handler.rfile.read1.return_value = b'a'
        with patch('backend.web.time.monotonic', side_effect=[100, 100, 100.1, 100.3]):
            handler.discard_rejected_body()
        self.assertEqual(handler.rfile.read1.call_count, 2)
        timeouts = [call.args[0] for call in handler.connection.settimeout.call_args_list]
        self.assertTrue(0 < timeouts[0] <= .25)
        self.assertTrue(0 < timeouts[1] <= .25)
        self.assertEqual(timeouts[-1], 7)

    def test_io_failure_restores_timeout_without_changing_error_response(self):
        handler = self.handler()
        handler.rfile = Mock()
        handler.rfile.read1.side_effect = ConnectionAbortedError('test transport closed')
        handler.dispatch(True)
        self.assertEqual(handler.send.call_args.args[0], 403)
        self.assertEqual(handler.connection.settimeout.call_args.args, (7,))
        self.assertTrue(handler.close_connection)

    def test_invalid_json_already_consumed_is_not_read_twice(self):
        handler = self.handler(b'{', host='127.0.0.1:12345')
        handler.discard_rejected_body = Mock(side_effect=AssertionError('must not read twice'))
        handler.dispatch(True)
        self.assertEqual(handler.send.call_args.args[0], 400)
        self.assertEqual(handler.rfile.tell(), 1)
        handler.discard_rejected_body.assert_not_called()

    def test_read_chunks_never_exceed_existing_size_limit(self):
        handler = self.handler(b'x' * 40000)
        handler.rfile = Mock(wraps=handler.rfile)
        handler.discard_rejected_body()
        requested = [call.args[0] for call in handler.rfile.read1.call_args_list]
        self.assertTrue(all(0 < size <= 8192 for size in requested))
        self.assertEqual(sum(requested), 40000)


if __name__ == '__main__':
    unittest.main()

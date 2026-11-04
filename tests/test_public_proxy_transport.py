"""System proxies may carry validated IP tunnels, never resolve arbitrary targets."""
import json
import unittest
from unittest.mock import Mock, patch
from backend.contracts import DomainError
from backend.public_dns import resolve_addresses
from backend.sources import fetch_public, public_url


class PublicProxyTransportTests(unittest.TestCase):
    def test_unicode_url_path_is_encoded_once(self):
        url=public_url('https://example.com/大疆%20Pocket?q=参数&x=1')
        self.assertEqual(url,'https://example.com/%E5%A4%A7%E7%96%86%20Pocket?q=%E5%8F%82%E6%95%B0&x=1')
        self.assertEqual(public_url(url),url)

    def test_proxy_dns_skips_blocked_system_dns_and_pins_resolver(self):
        packet={'Status':0,'Question':{'name':'example.com','type':1},'Answer':[{'name':'example.com','type':1,'data':'8.8.8.8'}]}
        conn=Mock();conn.getresponse.return_value=Mock(status=200)
        conn.getresponse.return_value.read.return_value=json.dumps(packet).encode()
        with patch('backend.public_dns.configured_proxy',return_value=('127.0.0.1',12450)),patch('socket.getaddrinfo') as dns,patch('http.client.HTTPSConnection',return_value=conn) as factory:
            self.assertEqual(resolve_addresses('example.com',443)[0][4],('8.8.8.8',443))
        dns.assert_not_called();factory.assert_called_once_with('127.0.0.1',12450,timeout=8)
        conn.set_tunnel.assert_called_once_with('223.5.5.5',443)

    def test_proxy_tunnel_target_is_public_ip_tls_and_host_are_original(self):
        conn=Mock();sock=conn.sock;response=Mock(status=200)
        response.getheader.side_effect=lambda key,default=None:{'Content-Type':'text/plain','Content-Encoding':'identity'}.get(key,default)
        response.read.side_effect=[b'public body',b''];conn.getresponse.return_value=response
        tls=Mock()
        with patch('backend.sources.resolve_public',return_value='8.8.8.8'),patch('backend.public_dns.configured_proxy',return_value=('127.0.0.1',12450)),patch('http.client.HTTPConnection',return_value=conn),patch('ssl.create_default_context',return_value=tls):
            self.assertEqual(fetch_public('https://example.com/正文')['text'],'public body')
        conn.set_tunnel.assert_called_once_with('8.8.8.8',443)
        tls.wrap_socket.assert_called_once_with(sock,server_hostname='example.com')
        self.assertEqual(conn.request.call_args.kwargs['headers']['Host'],'example.com')
        self.assertEqual(conn.request.call_args.args[1],'/%E6%AD%A3%E6%96%87')
        conn.close.assert_called_once()

    def test_private_literal_or_dns_answer_never_reaches_proxy(self):
        with patch('backend.public_dns.configured_proxy',return_value=('127.0.0.1',12450)),patch('http.client.HTTPSConnection') as doh:
            for host in ['127.0.0.1','198.18.0.1','10.0.0.1','foo.local','foo.internal.']:
                with self.subTest(host=host),self.assertRaises(DomainError):resolve_addresses(host,443)
            doh.assert_not_called()
        with patch('backend.sources.resolve_public',return_value='127.0.0.1'),patch('http.client.HTTPConnection') as conn:
            with self.assertRaises(DomainError):fetch_public('https://example.com/')
            conn.assert_not_called()

    def test_http_failures_have_safe_status_codes(self):
        for status,code in [(403,'SOURCE_HTTP_403'),(404,'SOURCE_HTTP_404'),(429,'SOURCE_HTTP_429'),(503,'SOURCE_HTTP_ERROR')]:
            conn=Mock();conn.getresponse.return_value=Mock(status=status)
            with self.subTest(status=status),patch('backend.sources.resolve_public',return_value='8.8.8.8'),patch('backend.public_dns.configured_proxy',return_value=None),patch('socket.create_connection'),patch('http.client.HTTPConnection',return_value=conn):
                with self.assertRaises(DomainError) as error:fetch_public('http://example.com/')
            self.assertEqual(error.exception.code,code)
            self.assertIn(str(status),str(error.exception))
            conn.getresponse.return_value.read.assert_not_called()

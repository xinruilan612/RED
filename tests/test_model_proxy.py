"""Offline proxy DNS/TLS boundaries: credentials only inside authenticated TLS."""
import socket
import ssl
import unittest
from unittest.mock import Mock, patch
from backend.contracts import DomainError
from backend.model_dns import resolve_model_addresses
from backend.provider import connected_request
from test_model_dns import HOST, PUBLIC_IP, SECRET, addresses, answer, dns_connection

PROXY=('127.0.0.1',12450)


class ModelProxyTests(unittest.TestCase):
    def test_official_proxy_dns_skips_os_and_uses_fixed_keyless_doh(self):
        dns=dns_connection()
        with patch('backend.model_dns.configured_proxy',return_value=PROXY), patch('socket.getaddrinfo') as system, patch('http.client.HTTPSConnection',return_value=dns) as https:
            self.assertEqual(resolve_model_addresses(HOST),addresses(PUBLIC_IP))
        system.assert_not_called();https.assert_called_once_with(*PROXY,timeout=8)
        dns.set_tunnel.assert_called_once_with('223.5.5.5',443)
        self.assertEqual(dns.request.call_args.args[0],'GET')
        self.assertNotIn(SECRET,str(dns.mock_calls));dns.close.assert_called_once()

    def test_custom_hosts_never_use_doh_and_private_system_answers_reject(self):
        for host in ('custom.example.com','api.deepseek.com.evil.test','localhost','127.0.0.1'):
            for rows in (addresses('127.0.0.1'),addresses('198.18.0.8')):
                with self.subTest(host=host,rows=rows), patch('backend.model_dns.configured_proxy',return_value=PROXY), patch('socket.getaddrinfo',return_value=rows), patch('http.client.HTTPSConnection') as doh:
                    with self.assertRaises(DomainError) as raised:resolve_model_addresses(host)
                    self.assertEqual(raised.exception.code,'MODEL_REQUEST_NOT_SENT');doh.assert_not_called()

    def test_proxy_dns_rejects_private_multicast_wrong_host_and_cname_cycle(self):
        packets=[answer(ip=ip) for ip in ('127.0.0.1','10.0.0.1','169.254.169.254','198.18.0.8','224.0.0.1')]
        packets.append(answer(host='unrelated.example.com'))
        cycle=answer();cycle['Answer']=[{'name':HOST,'type':5,'data':HOST}];packets.append(cycle)
        for packet in packets:
            with self.subTest(packet=packet), patch('backend.model_dns.configured_proxy',return_value=PROXY), patch('http.client.HTTPSConnection',return_value=dns_connection(packet)), patch('socket.getaddrinfo') as system:
                with self.assertRaises(DomainError) as raised:resolve_model_addresses(HOST)
                self.assertEqual(raised.exception.code,'MODEL_REQUEST_NOT_SENT');system.assert_not_called()

    def test_tunnel_targets_pinned_ip_then_tls_uses_original_host(self):
        conn=dns_connection({'ok':True});plain=conn.sock;tls=Mock();events=[]
        conn.connect.side_effect=lambda:events.append('connect')
        context=Mock()
        def wrap(sock,server_hostname):
            self.assertIs(sock,plain);self.assertEqual(server_hostname,HOST)
            events.append('tls');return tls
        context.wrap_socket.side_effect=wrap
        conn.request.side_effect=lambda *args,**kwargs:events.append('post')
        with patch('backend.model_dns.resolve_model_addresses',return_value=addresses(PUBLIC_IP)), patch('backend.public_dns.configured_proxy',return_value=PROXY), patch('http.client.HTTPConnection',return_value=conn) as http, patch('ssl.create_default_context',return_value=context):
            result=connected_request('https://'+HOST+'/chat/completions',{'Authorization':'Bearer '+SECRET},{'messages':['private prompt']})
        self.assertEqual(result,{'ok':True});http.assert_called_once_with(*PROXY,timeout=90)
        conn.set_tunnel.assert_called_once_with(PUBLIC_IP,443)
        self.assertEqual(events,['connect','tls','post']);self.assertIs(conn.sock,tls)
        self.assertEqual(conn.auto_open,0)
        self.assertEqual(conn.request.call_args.args[3]['Host'],HOST)
        self.assertIn(SECRET,conn.request.call_args.args[3]['Authorization'])
        self.assertNotIn(SECRET,str(conn.set_tunnel.call_args));conn.close.assert_called_once()

    def test_failed_connect_or_tls_sends_no_post_or_secret_and_is_not_sent(self):
        for phase in ('connect','tls'):
            conn=dns_connection();context=Mock()
            if phase=='connect':conn.connect.side_effect=OSError('proxy unavailable')
            else:context.wrap_socket.side_effect=ssl.SSLCertVerificationError('bad certificate')
            with self.subTest(phase=phase), patch('backend.model_dns.resolve_model_addresses',return_value=addresses(PUBLIC_IP)), patch('backend.public_dns.configured_proxy',return_value=PROXY), patch('http.client.HTTPConnection',return_value=conn), patch('ssl.create_default_context',return_value=context):
                with self.assertRaises(DomainError) as raised:
                    connected_request('https://'+HOST+'/chat/completions',{'Authorization':'Bearer '+SECRET},{'messages':['private prompt']})
                self.assertEqual(raised.exception.code,'MODEL_REQUEST_NOT_SENT')
                conn.request.assert_not_called();conn.close.assert_called_once()
                self.assertNotIn(SECRET,str(conn.mock_calls));self.assertNotIn('private prompt',str(conn.mock_calls))

    def test_proxy_post_timeout_or_redirect_never_retries(self):
        for failure in ('timeout','redirect'):
            conn=dns_connection(status=302)
            if failure=='timeout':conn.getresponse.side_effect=TimeoutError()
            with self.subTest(failure=failure), patch('backend.model_dns.resolve_model_addresses',return_value=addresses(PUBLIC_IP)), patch('backend.public_dns.configured_proxy',return_value=PROXY), patch('http.client.HTTPConnection',return_value=conn), patch('ssl.create_default_context'):
                with self.assertRaises(DomainError) as raised:
                    connected_request('https://'+HOST+'/chat/completions',{'Authorization':'Bearer '+SECRET},{})
                self.assertEqual(raised.exception.code,'PROVIDER_ERROR')
                self.assertEqual(conn.request.call_count,1);conn.close.assert_called_once()

    def test_transport_defensively_rejects_any_nonpublic_pinned_answer(self):
        for rows in (addresses('127.0.0.1'),addresses(PUBLIC_IP,'10.0.0.1'),addresses('224.0.0.1')):
            with self.subTest(rows=rows), patch('backend.model_dns.resolve_model_addresses',return_value=rows), patch('backend.public_dns.configured_proxy',return_value=PROXY), patch('http.client.HTTPConnection') as http:
                with self.assertRaises(DomainError) as raised:
                    connected_request('https://'+HOST+'/chat/completions',{'Authorization':'Bearer '+SECRET},{})
                self.assertEqual(raised.exception.code,'MODEL_REQUEST_NOT_SENT');http.assert_not_called()

    def test_invalid_proxy_configuration_is_not_a_billable_attempt(self):
        invalid=DomainError('SOURCE_UNAVAILABLE','unsupported proxy')
        with patch('backend.model_dns.configured_proxy',side_effect=invalid), patch('socket.getaddrinfo') as system:
            with self.assertRaises(DomainError) as raised:resolve_model_addresses(HOST)
            self.assertEqual(raised.exception.code,'MODEL_REQUEST_NOT_SENT');system.assert_not_called()
        with patch('backend.model_dns.resolve_model_addresses',return_value=addresses(PUBLIC_IP)), patch('backend.public_dns.configured_proxy',side_effect=invalid), patch('http.client.HTTPConnection') as http:
            with self.assertRaises(DomainError) as raised:connected_request('https://'+HOST+'/chat/completions',{}, {})
            self.assertEqual(raised.exception.code,'MODEL_REQUEST_NOT_SENT');http.assert_not_called()

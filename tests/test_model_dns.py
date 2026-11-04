"""Offline DNS/transport security regressions; never contact a model service."""
import copy
import json
import socket
import unittest
from unittest.mock import Mock, patch

from backend.contracts import DomainError
from backend.provider import connected_request
from backend.model_dns import resolve_model_addresses


HOST = 'api.deepseek.com'
FAKE_IP = '198.18.0.8'
PUBLIC_IP = '1.1.1.1'
SECRET = 'test-key-never-send-to-dns'


def addresses(*ips):
    return [(socket.AF_INET6 if ':' in ip else socket.AF_INET, socket.SOCK_STREAM,
             socket.IPPROTO_TCP, '', (ip, 443, 0, 0) if ':' in ip else (ip, 443)) for ip in ips]


def answer(host=HOST, ip=PUBLIC_IP):
    return {'Status': 0, 'Question': [{'name': host, 'type': 1}],
            'Answer': [{'name': host, 'type': 1, 'TTL': 60, 'data': ip}]}


def dns_connection(packet=None, status=200, raw=None):
    response = Mock(status=status)
    response.read.return_value = raw if raw is not None else json.dumps(packet if packet is not None else answer()).encode()
    conn = Mock()
    conn.getresponse.return_value = response
    return conn


class ModelDNSTests(unittest.TestCase):
    def setUp(self):
        for target in ('backend.model_dns.configured_proxy','backend.public_dns.configured_proxy'):
            stub=patch(target,return_value=None);stub.start();self.addCleanup(stub.stop)

    def test_public_system_dns_is_unchanged_and_never_uses_auxiliary_dns(self):
        resolved = addresses(PUBLIC_IP, '2606:4700:4700::1111')
        for host in (HOST, 'custom.example.com'):
            with self.subTest(host=host), patch('socket.getaddrinfo', return_value=resolved), patch('http.client.HTTPSConnection') as https:
                self.assertEqual(resolve_model_addresses(host), resolved)
                https.assert_not_called()

    def test_fake_ip_for_exact_official_host_uses_only_keyless_https_get(self):
        conn = dns_connection()
        with patch('socket.getaddrinfo', return_value=addresses(FAKE_IP)), patch('http.client.HTTPSConnection', return_value=conn) as https:
            resolved = resolve_model_addresses(HOST)
        self.assertEqual([item[4][0] for item in resolved], [PUBLIC_IP])
        https.assert_called_once_with('223.5.5.5', timeout=8)
        self.assertEqual(conn.request.call_count, 1)
        call = conn.request.call_args
        self.assertEqual(call.args[:2], ('GET', '/resolve?name=api.deepseek.com&type=A'))
        self.assertNotIn('Authorization', str(call))
        self.assertNotIn('api-key', str(call).lower())
        if len(call.args) > 2:
            self.assertIsNone(call.args[2])
        conn.close.assert_called_once()

    def test_alidns_object_question_resolves_and_rejects_boolean_protocol_fields(self):
        packet = answer(ip='8.140.217.18')
        packet['Question'] = packet['Question'][0]
        with patch('socket.getaddrinfo', return_value=addresses(FAKE_IP)), patch('http.client.HTTPSConnection', return_value=dns_connection(packet)):
            self.assertEqual(resolve_model_addresses(HOST)[0][4][0], '8.140.217.18')
        for field in ('Status', 'question_type'):
            invalid = copy.deepcopy(packet)
            if field == 'Status':
                invalid['Status'] = False
            else:
                invalid['Question']['type'] = True
            with self.subTest(field=field), patch('socket.getaddrinfo', return_value=addresses(FAKE_IP)), patch('http.client.HTTPSConnection', return_value=dns_connection(invalid)):
                with self.assertRaises(DomainError):
                    resolve_model_addresses(HOST)

    def test_private_mixed_and_non_allowlisted_fake_dns_fail_before_connections(self):
        cases = [(HOST, ips) for ips in (
            ['127.0.0.1'], ['10.0.0.1'], ['169.254.169.254'], ['::1'], ['fc00::1'],
            ['100.64.0.1'], ['0.0.0.0'], [FAKE_IP, PUBLIC_IP], [FAKE_IP, '10.0.0.1'],
            [PUBLIC_IP, '127.0.0.1'], [])]
        cases += [(host, [FAKE_IP]) for host in ('custom.example.com', 'api.deepseek.com.evil.test', 'sub.api.deepseek.com', '198.18.0.8')]
        for host, ips in cases:
            with self.subTest(host=host, ips=ips), patch('socket.getaddrinfo', return_value=addresses(*ips)), patch('http.client.HTTPSConnection') as https:
                with self.assertRaises(DomainError):
                    resolve_model_addresses(host)
                https.assert_not_called()

    def test_both_ends_of_fake_ip_range_can_use_fallback(self):
        for ip in ('198.18.0.0', '198.19.255.255'):
            with self.subTest(ip=ip), patch('socket.getaddrinfo', return_value=addresses(ip)), patch('http.client.HTTPSConnection', return_value=dns_connection()):
                self.assertEqual(resolve_model_addresses(HOST)[0][4][0], PUBLIC_IP)

    def test_system_dns_failure_does_not_activate_auxiliary_dns(self):
        with patch('socket.getaddrinfo', side_effect=socket.gaierror('offline')), patch('http.client.HTTPSConnection') as https:
            with self.assertRaises(DomainError):
                resolve_model_addresses(HOST)
            https.assert_not_called()

    def test_dns_failure_never_opens_model_connection_or_sends_key(self):
        for conn in (dns_connection(status=302), dns_connection(status=500), dns_connection(raw=b'not json')):
            with self.subTest(conn=conn), patch('socket.getaddrinfo', return_value=addresses(FAKE_IP)), patch('http.client.HTTPSConnection', return_value=conn) as https:
                with self.assertRaises(DomainError) as caught:
                    connected_request('https://' + HOST + '/chat/completions', {'Authorization': 'Bearer ' + SECRET}, {'messages': ['private prompt']})
                self.assertEqual(https.call_count, 1)
                self.assertEqual(https.call_args.args[0], '223.5.5.5')
                self.assertEqual(conn.request.call_count, 1)
                self.assertEqual(conn.request.call_args.args[0], 'GET')
                self.assertNotIn(SECRET, str(conn.mock_calls))
                self.assertNotIn('private prompt', str(conn.mock_calls))
                self.assertNotIn(SECRET, str(caught.exception))
                conn.close.assert_called_once()

    def test_dns_invalid_response_shapes_and_records_fail_closed(self):
        packets = [[], {}, {'Status': 2}, answer(host='other.example.com')]
        p = answer(); p['Question'][0]['type'] = 28; packets.append(p)
        p = answer(); p['TC'] = True; packets.append(p)
        p = answer(); p['Question'][0]['name'] = None; packets.append(p)
        p = answer(); p['Question'] = []; packets.append(p)
        p = answer(); p['Answer'] = []; packets.append(p)
        p = answer(); p['Answer'][0]['name'] = 'unrelated.example.com'; packets.append(p)
        p = answer(); p['Answer'][0]['data'] = 'not-an-ip'; packets.append(p)
        p = answer(); p['Answer'][0]['type'] = 28; packets.append(p)
        for ip in ('127.0.0.1', '10.0.0.1', '169.254.169.254', FAKE_IP, '100.64.0.1'):
            packets.append(answer(ip=ip))
            p = answer(); p['Answer'].append({'name': HOST, 'type': 1, 'data': ip}); packets.append(p)
        for packet in packets:
            conn = dns_connection(packet=packet)
            with self.subTest(packet=packet), patch('socket.getaddrinfo', return_value=addresses(FAKE_IP)), patch('http.client.HTTPSConnection', return_value=conn):
                with self.assertRaises(DomainError):
                    resolve_model_addresses(HOST)
                conn.close.assert_called_once()

    def test_valid_cname_chain_resolves_only_associated_public_answers(self):
        packet = answer()
        packet['Answer'] = [
            {'name': HOST, 'type': 5, 'data': 'first.cdn.example.com.'},
            {'name': 'first.cdn.example.com.', 'type': 5, 'data': 'last.cdn.example.com.'},
            {'name': 'last.cdn.example.com.', 'type': 1, 'data': PUBLIC_IP}]
        conn = dns_connection(packet)
        with patch('socket.getaddrinfo', return_value=addresses(FAKE_IP)), patch('http.client.HTTPSConnection', return_value=conn):
            self.assertEqual(resolve_model_addresses(HOST)[0][4][0], PUBLIC_IP)
        for bad_records in (
            [{'name': HOST, 'type': 5, 'data': 'first.cdn.example.com'}, {'name': 'first.cdn.example.com', 'type': 5, 'data': HOST}],
            [{'name': 'unrelated.example.com', 'type': 1, 'data': PUBLIC_IP}],
            packet['Answer'] + [{'name': 'unrelated.example.com', 'type': 1, 'data': PUBLIC_IP}],
            packet['Answer'] + [{'name': HOST, 'type': 5, 'data': 'conflicting.example.com'}],
        ):
            invalid = copy.deepcopy(packet); invalid['Answer'] = bad_records
            with self.subTest(records=bad_records), patch('socket.getaddrinfo', return_value=addresses(FAKE_IP)), patch('http.client.HTTPSConnection', return_value=dns_connection(invalid)):
                with self.assertRaises(DomainError):
                    resolve_model_addresses(HOST)

    def test_oversized_dns_response_is_bounded_and_rejected(self):
        conn = dns_connection(raw=b' ' * 65537)
        with patch('socket.getaddrinfo', return_value=addresses(FAKE_IP)), patch('http.client.HTTPSConnection', return_value=conn):
            with self.assertRaises(DomainError):
                resolve_model_addresses(HOST)
        conn.getresponse.return_value.read.assert_called_once_with(65537)
        conn.close.assert_called_once()

    def test_auxiliary_timeout_fails_closed_and_closes_connection(self):
        conn = dns_connection(); conn.getresponse.side_effect = TimeoutError('offline')
        with patch('socket.getaddrinfo', return_value=addresses(FAKE_IP)), patch('http.client.HTTPSConnection', return_value=conn):
            with self.assertRaises(DomainError):
                resolve_model_addresses(HOST)
        conn.close.assert_called_once()

    def test_transport_pins_auxiliary_public_ip_with_original_tls_host(self):
        dns = dns_connection()
        model = dns_connection({'ok': True})
        with patch('socket.getaddrinfo', return_value=addresses(FAKE_IP)), patch('http.client.HTTPSConnection', side_effect=[dns, model]) as https, patch('socket.create_connection') as socket_connect:
            result = connected_request('https://' + HOST + '/chat/completions', {'Authorization': 'Bearer ' + SECRET}, {'model': 'example'})
            model._create_connection((HOST, 443), 90)
        self.assertEqual(result, {'ok': True})
        self.assertEqual(https.call_args_list[1].args[:2], (HOST, 443))
        socket_connect.assert_called_once_with((PUBLIC_IP, 443), 90, None)
        self.assertEqual(model.request.call_count, 1)
        self.assertEqual(model.request.call_args.args[:2], ('POST', '/chat/completions'))
        self.assertNotIn(SECRET, str(dns.mock_calls))
        self.assertIn(SECRET, str(model.request.call_args))
        model.close.assert_called_once()

    def test_model_post_timeout_is_never_retried(self):
        model = dns_connection(); model.getresponse.side_effect = TimeoutError('unknown usage')
        with patch('socket.getaddrinfo', return_value=addresses(PUBLIC_IP)), patch('http.client.HTTPSConnection', return_value=model) as https:
            with self.assertRaises(DomainError) as caught:
                connected_request('https://' + HOST + '/chat/completions', {'Authorization': 'Bearer ' + SECRET}, {})
        self.assertEqual(https.call_count, 1)
        self.assertEqual(model.request.call_count, 1)
        self.assertNotIn(SECRET, str(caught.exception))
        model.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()

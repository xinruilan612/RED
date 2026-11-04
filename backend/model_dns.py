"""Public-only model DNS, with narrow recovery from proxy benchmark addresses.

Only built-in vendor hostnames qualify, when an HTTP proxy is configured or
every OS DNS address is in 198.18.0.0/15. The resolver receives a hostname, never
model keys or prompts. Neither DNS response redirects nor model POSTs retry.
"""
import http.client
import ipaddress
import json
import socket
from urllib.parse import urlencode, urlsplit

from backend.contracts import DomainError, require
from backend.public_dns import configured_proxy, allowed_address

FAKE_IP = ipaddress.ip_network('198.18.0.0/15')
DNS_SERVER = '223.5.5.5'
DNS_LIMIT = 65536


def _public_answer(packet, host):
    require(isinstance(packet, dict) and type(packet.get('Status')) is int and packet['Status'] == 0
            and not packet.get('TC'), 'MODEL_REQUEST_NOT_SENT', '独立 DNS 未返回完整解析结果，请稍后重试连接。')
    question = packet.get('Question')
    # AliDNS returns an object; other JSON DoH implementations use a one-item list.
    if isinstance(question, dict):
        question = [question]
    require(isinstance(question, list) and len(question) == 1
            and isinstance(question[0], dict) and type(question[0].get('type')) is int and question[0]['type'] == 1
            and question[0].get('name', '').lower().rstrip('.') == host,
            'MODEL_REQUEST_NOT_SENT', '独立 DNS 返回的域名不匹配，请稍后重试连接。')
    records = packet.get('Answer')
    require(isinstance(records, list) and 0 < len(records) <= 64
            and all(isinstance(r, dict) and type(r.get('type')) is int for r in records),
            'MODEL_REQUEST_NOT_SENT', '独立 DNS 没有可用地址，请检查网络后重试连接。')
    aliases = {}
    for row in records:
        require(isinstance(row.get('name'), str) and isinstance(row.get('data'), str),
                'MODEL_REQUEST_NOT_SENT', '独立 DNS 返回格式无效，请稍后重试连接。')
        if row.get('type') == 5:
            name, target = row['name'].lower().rstrip('.'), row['data'].lower().rstrip('.')
            require(name not in aliases or aliases[name] == target, 'MODEL_REQUEST_NOT_SENT', '独立 DNS 别名冲突，请稍后重试连接。')
            aliases[name] = target
    reachable, current = set(), host
    for _ in range(65):
        require(current not in reachable, 'MODEL_REQUEST_NOT_SENT', '独立 DNS 别名循环，请稍后重试连接。')
        reachable.add(current)
        if current not in aliases:
            break
        current = aliases[current]
    require(set(aliases) <= reachable, 'MODEL_REQUEST_NOT_SENT', '独立 DNS 返回了无关别名，请稍后重试连接。')
    addresses = []
    for row in records:
        if row.get('type') != 1:
            continue
        require(row['name'].lower().rstrip('.') == current,
                'MODEL_REQUEST_NOT_SENT', '独立 DNS 返回了无关地址，请稍后重试连接。')
        address = ipaddress.ip_address(row['data'])
        require(address.version == 4 and allowed_address(str(address)), 'MODEL_REQUEST_NOT_SENT',
                '独立 DNS 仍返回非公网地址，请检查网络或联系网络管理员；尚未发送模型请求。')
        if str(address) not in addresses:
            addresses.append(str(address))
    require(addresses, 'MODEL_REQUEST_NOT_SENT', '独立 DNS 没有可用公网地址，请检查网络后重试连接。')
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (a, 443)) for a in addresses]


def resolve_model_addresses(host):
    try:
        from backend.model_connections import PROVIDERS
        official = {urlsplit(p['base_url']).hostname for p in PROVIDERS.values() if p['base_url']}
        # Custom hosts cannot use this fallback, even with a configured proxy.
        proxy=configured_proxy(host) if host in official else None
        if not proxy:
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            ips = [ipaddress.ip_address(a[4][0]) for a in addresses]
            if ips and all(allowed_address(str(ip)) for ip in ips):
                return addresses
            fallback = host in official and ips and all(ip.version == 4 and ip in FAKE_IP for ip in ips)
            require(fallback, 'MODEL_REQUEST_NOT_SENT',
                    f'模型域名 {host} 解析为非公网地址。请使用厂商的公网 HTTPS 接口；若地址正确，请检查 VPN 或 DNS 设置后重试。尚未发送模型请求。')
        conn = http.client.HTTPSConnection(*(proxy or (DNS_SERVER,)), timeout=8)
        try:
            if proxy:conn.set_tunnel(DNS_SERVER,443)
            conn.request('GET', '/resolve?' + urlencode({'name': host, 'type': 'A'}),
                         headers={'Accept': 'application/dns-json'})
            response = conn.getresponse()
            require(response.status == 200, 'MODEL_REQUEST_NOT_SENT',
                    '系统 DNS 返回虚拟地址，独立解析服务暂不可用。请检查网络或关闭 VPN 后重试；尚未发送模型请求。')
            raw = response.read(DNS_LIMIT + 1)
            require(len(raw) <= DNS_LIMIT, 'MODEL_REQUEST_NOT_SENT', '独立 DNS 响应异常，请稍后重试连接。')
            return _public_answer(json.loads(raw), host)
        finally:
            conn.close()
    except DomainError as error:
        if error.code=='MODEL_REQUEST_NOT_SENT':raise
        raise DomainError('MODEL_REQUEST_NOT_SENT','模型代理或DNS配置不可用；尚未发送模型请求。') from None
    except (OSError, ValueError, TypeError, AttributeError, http.client.HTTPException):
        raise DomainError('MODEL_REQUEST_NOT_SENT',
                          '无法安全解析模型域名。请检查网络、VPN 或 DNS 设置后重新测试；当前配置已保留，尚未发送模型请求。') from None

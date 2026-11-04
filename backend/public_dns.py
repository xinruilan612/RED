"""Public-only web DNS with bounded DoH recovery and system HTTP proxy support."""
import http.client
import ipaddress
import json
import os
import socket
from urllib.parse import urlencode, urlsplit
from urllib.request import getproxies, proxy_bypass
from backend.contracts import require, DomainError

FAKE_RANGE = ipaddress.ip_network('198.18.0.0/15')
# Operators whose OS proxy is broken (or absent) can force a direct, still
# IP-pinned, TLS-verified connection without changing the system settings.
DIRECT_ENV = 'YOUJI_DIRECT_CONNECT'


def direct_requested():
    return os.environ.get(DIRECT_ENV, '').strip().lower() in ('1', 'true', 'yes', 'on')


def allowed_address(text):
    address = ipaddress.ip_address(text)
    return (address.is_global and not address.is_multicast
            and not getattr(address, 'ipv4_mapped', None)
            and not getattr(address, 'sixtofour', None))


def configured_proxy(host, scheme='https'):
    """Use the OS/environment proxy only as transport, never as target resolver."""
    if direct_requested():
        return None
    if proxy_bypass(host):
        return None
    value = getproxies().get(scheme)
    if not value:
        return None
    parsed = urlsplit(value if '://' in value else 'http://' + value)
    require(parsed.scheme == 'http' and parsed.hostname and not parsed.username and not parsed.password,
            'SOURCE_UNAVAILABLE', '公开网页读取需要无认证 HTTP 系统代理')
    return parsed.hostname, parsed.port or 80


def resolve_addresses(host, port):
    """Resolve via trusted DoH when proxied; reject every non-public target."""
    try:
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            require(allowed_address(host), 'FORBIDDEN', '不能读取本机、内网或保留网络地址')
            family = socket.AF_INET6 if literal.version == 6 else socket.AF_INET
            return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (host, port))]
        require(isinstance(host, str) and '.' in host and
                not host.lower().rstrip('.').endswith(('.localhost', '.local', '.internal')),
                'FORBIDDEN', '不能读取本机或内网地址')
        proxy = configured_proxy(host)
        if not proxy:
            try:
                rows = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            except socket.gaierror:
                rows = []
            if rows and all(allowed_address(row[4][0]) for row in rows):
                return rows
            if rows:
                ips = [ipaddress.ip_address(row[4][0]) for row in rows]
                require(all(ip.version == 4 and ip in FAKE_RANGE for ip in ips),
                        'FORBIDDEN', '不能读取本机、内网或保留网络地址')
        # A configured proxy can reach the fixed public resolver without OS DNS.
        # HTTPSConnection authenticates the resolver IP after CONNECT.
        connection = http.client.HTTPSConnection(*(proxy or ('223.5.5.5',)), timeout=8)
        if proxy:
            connection.set_tunnel('223.5.5.5', 443)
        try:
            connection.request('GET', '/resolve?' + urlencode({'name': host, 'type': 'A'}),
                               headers={'Accept': 'application/dns-json'})
            response = connection.getresponse()
            require(response.status == 200, 'SOURCE_UNAVAILABLE', '独立网页 DNS 暂不可用；未读取来源正文')
            raw = response.read(65537)
            require(len(raw) <= 65536, 'SOURCE_UNAVAILABLE', '独立网页 DNS 响应过大')
            from backend.model_dns import _public_answer
            try:
                parsed = _public_answer(json.loads(raw), host.lower().rstrip('.'))
            except DomainError:
                raise DomainError('SOURCE_UNAVAILABLE', '独立网页 DNS 未返回有效匹配的公网地址') from None
            require(all(allowed_address(row[4][0]) for row in parsed), 'FORBIDDEN', '来源解析到了不允许访问的网络')
            return [(family, kind, proto, canon, (addr[0], port)) for family, kind, proto, canon, addr in parsed]
        finally:
            connection.close()
    except DomainError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, http.client.HTTPException):
        raise DomainError('SOURCE_UNAVAILABLE', '公开网页域名解析失败，未读取来源正文；请检查网络后重试') from None

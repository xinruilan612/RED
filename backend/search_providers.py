"""Bounded, selectable web research. Site scope is not a platform data API."""
import json
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from urllib.request import Request, build_opener
from uuid import uuid4

from backend import sources
from backend.contracts import DomainError, require
from backend.provider import NoRedirect

TARGETS = {
    'web': {'name': '全网', 'domains': []},
    'xiaohongshu': {'name': '小红书公开搜索线索', 'domains': ['xiaohongshu.com']},
    'jd': {'name': '京东公开商品网页', 'domains': ['jd.com']},
    'taobao': {'name': '淘宝 / 天猫公开商品网页', 'domains': ['taobao.com', 'tmall.com']},
}
BAIDU_URL = 'https://qianfan.baidubce.com/v2/ai_search/web_search'
BAIDU_DOCS = 'https://ai.baidu.com/ai-doc/AppBuilder/pmaxd1hvy'


def target_domains(targets):
    require(isinstance(targets, list) and 1 <= len(targets) <= len(TARGETS)
            and all(isinstance(t, str) and t in TARGETS for t in targets),
            'INVALID_INPUT', '请选择有效的搜索范围')
    require('web' not in targets or len(targets) == 1,
            'INVALID_INPUT', '全网搜索不能与限定平台同时选择')
    return list(dict.fromkeys(d for t in targets for d in TARGETS[t]['domains']))


def within_domains(url, domains):
    host = (urlsplit(url).hostname or '').lower()
    return not domains or any(host == d or host.endswith('.' + d) for d in domains)


def request_baidu(payload, api_key):
    require(isinstance(api_key, str) and api_key.strip(), 'KEY_REQUIRED', '请先配置百度搜索 API Key')
    request = Request(BAIDU_URL, json.dumps(payload).encode(),
                      {'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'})
    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            body = response.read(1_000_001)
        require(len(body) <= 1_000_000, 'SOURCE_UNAVAILABLE', '搜索结果超过大小限制')
        packet = json.loads(body)
        require(isinstance(packet, dict) and isinstance(packet.get('references'), list),
                'SOURCE_UNAVAILABLE', '百度搜索未返回可用来源；未自动重试')
        return packet
    except DomainError:
        raise
    except (HTTPError, URLError, OSError, ValueError):
        # Never expose provider messages, request headers or API keys.
        raise DomainError('SOURCE_UNAVAILABLE', '百度搜索失败或超时，可能已产生费用；未自动重试') from None


def search(query, provider='bing', targets=None, api_key=None, transport=None):
    require(isinstance(query, str) and 2 <= len(query.strip()) <= 120,
            'INVALID_INPUT', '搜索词需为 2 至 120 个字符')
    targets = targets if targets is not None else ['web']
    domains = target_domains(targets)
    require(provider in ('bing', 'wikipedia', 'baidu'), 'INVALID_INPUT', '搜索服务无效')
    if provider == 'wikipedia':
        require(not domains, 'INVALID_INPUT', '百科搜索仅支持全网背景资料范围')
        result = sources.search_web(query, provider=provider)
    elif provider == 'bing':
        def scoped_fetch(url):
            parts = urlsplit(url)
            params = parse_qs(parts.query)
            if domains:
                params['q'] = [params['q'][0] + ' (' + ' OR '.join('site:' + d for d in domains) + ')']
            return (transport or sources.fetch_search)(urlunsplit((parts.scheme, parts.netloc, parts.path,
                                                                  urlencode(params, doseq=True), '')))
        result = sources.search_web(query, fetch=scoped_fetch)
        if domains:
            result['effective_query'] = result.get('effective_query', query) + ' (' + ' OR '.join('site:' + d for d in domains) + ')'
    else:
        payload = {'messages': [{'role': 'user', 'content': query.strip()}],
                   'search_source': 'baidu_search_v2', 'resource_type_filter': [{'type': 'web', 'top_k': 20}]}
        if domains:
            payload['search_filter'] = {'match': {'site': domains}}
        packet = (transport or request_baidu)(payload, api_key)
        require(isinstance(packet, dict) and isinstance(packet.get('references'), list),
                'SOURCE_UNAVAILABLE', '百度搜索返回格式无效')
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        seen = set()
        for row in packet['references'][:100]:
            if not isinstance(row, dict):
                continue
            try:
                url = sources.public_url(row.get('url'))
            except DomainError:
                continue
            if url in seen or not within_domains(url, domains):
                continue
            seen.add(url)
            rows.append({'title': str(row.get('title') or '搜索线索')[:200], 'url': url,
                         'snippet': str(row.get('content') or '')[:600], 'body_read': False,
                         'fetched_at': now, 'published_at': None, 'source_type': 'search_result'})
            if len(rows) == 8:
                break
        result = {'query': query, 'provider': '百度 AI 搜索 · 官方搜索接口', 'searched_at': now,
                  'results': rows, 'note': '搜索摘要是线索；正文须单独读取。网页日期与平台热度未核实。'}
    result['results'] = [r for r in result['results'] if within_domains(r['url'], domains)]
    result['targets'] = targets
    result['coverage'] = '搜索引擎收录范围，不是平台站内完整搜索、实时热榜或商品库存接口'
    return result


class SearchSettings:
    """User-owned search credential and conservative daily request reservation."""
    def __init__(self, store, vault=None):
        self.store, self._vault = store, vault

    def vault(self):
        if self._vault is None:
            from backend.credentials import CredentialVault
            self._vault = CredentialVault(self.store)
        return self._vault

    def public(self, owner):
        with self.store.connect() as db:
            row = db.execute('SELECT enabled,day_limit,version FROM search_connections WHERE owner=?', (owner,)).fetchone()
            used = db.execute('SELECT COUNT(*) FROM search_requests WHERE owner=? AND created_at>=?',
                              (owner, self.day_start())).fetchone()[0]
        # Configuration is permission to attempt a request, not a live health
        # check. Do not probe vendors (possibly paid) while rendering settings.
        providers = []
        for identity, name in [('bing', 'Bing 公开网页（实验）'),
                               ('wikipedia', '百科背景资料'), ('baidu', '百度 AI 搜索')]:
            can_attempt = identity != 'baidu' or bool(row and row[0])
            providers.append({'id': identity, 'name': name, 'ready': False,
                              'configurable': identity == 'baidu',
                              'configured': identity != 'baidu' or row is not None,
                              'can_attempt': can_attempt, 'verification_status': 'not_verified',
                              'verified_at': None,
                              'status_note': ('可尝试，当前连接未核验' if can_attempt else
                                              '请在模型与搜索设置中配置并启用；当前连接未核验')})
        return {'providers': providers,
                'targets': [{'id': k, **v, 'native_api_connected': False,
                             'access_mode': 'search_engine_domain_filter' if v['domains'] else 'search_engine',
                             'status_note': '仅搜索引擎域名过滤，未接通平台专用接口' if v['domains'] else '搜索引擎公开收录范围'}
                            for k, v in TARGETS.items()],
                'baidu': {'configured': row is not None, 'enabled': bool(row and row[0]),
                          'day_limit': row[1] if row else 20, 'version': row[2] if row else 0,
                          'requests_today': used, 'docs': BAIDU_DOCS}}

    @staticmethod
    def day_start():
        # Daily budget is deliberately fixed to UTC, stated in the settings UI.
        return int(time.time()) // 86400 * 86400

    def save(self, owner, data):
        require(isinstance(data, dict) and {'enabled', 'day_limit', 'version'} <= set(data)
                <= {'enabled', 'day_limit', 'version', 'api_key', 'acknowledge_cost'},
                'INVALID_INPUT', '搜索配置字段无效')
        require(type(data['enabled']) is bool and type(data['day_limit']) is int
                and 1 <= data['day_limit'] <= 1000 and type(data['version']) is int,
                'INVALID_INPUT', '搜索配置或每日次数上限无效')
        if data['enabled']:
            require(data.get('acknowledge_cost') is True, 'INVALID_INPUT', '请确认百度搜索可能按服务商规则计费')
        new_secret = None
        if data.get('api_key'):
            key = data['api_key']
            require(isinstance(key, str) and 8 <= len(key) <= 4096 and not any(c.isspace() for c in key),
                    'INVALID_INPUT', '搜索 API Key 格式无效')
            new_secret = self.vault().encrypt(key)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT secret,version FROM search_connections WHERE owner=?', (owner,)).fetchone()
            require(data['version'] == (row[1] if row else 0), 'VERSION_CONFLICT', '搜索配置已更新，请刷新')
            secret = new_secret or (row[0] if row else None)
            require(secret, 'KEY_REQUIRED', '首次配置需要填写搜索 API Key')
            db.execute('INSERT INTO search_connections(owner,secret,enabled,day_limit,version) VALUES(?,?,?,?,?) '
                       'ON CONFLICT(owner) DO UPDATE SET secret=excluded.secret,enabled=excluded.enabled,day_limit=excluded.day_limit,version=excluded.version',
                       (owner, secret, int(data['enabled']), data['day_limit'], data['version'] + 1))
        return self.public(owner)

    def search(self, owner, query, provider='bing', targets=None):
        # Validate before reserving quota. Failures still consume reservations:
        # a timeout is not evidence that the vendor did not charge the request.
        require(isinstance(query, str) and 2 <= len(query.strip()) <= 120, 'INVALID_INPUT', '搜索词需为 2 至 120 个字符')
        target_domains(targets if targets is not None else ['web'])
        key = None
        if provider == 'baidu':
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT secret,enabled,day_limit FROM search_connections WHERE owner=?', (owner,)).fetchone()
                require(row and row[1], 'KEY_REQUIRED', '请先在模型与搜索设置中启用自己的百度搜索连接')
                used = db.execute('SELECT COUNT(*) FROM search_requests WHERE owner=? AND created_at>=?',
                                  (owner, self.day_start())).fetchone()[0]
                require(used < row[2], 'BUDGET_EXCEEDED', '已达到今天的百度搜索次数上限（UTC）')
                key = self.vault().decrypt(row[0])
                db.execute('INSERT INTO search_requests(id,owner,created_at) VALUES(?,?,?)', (str(uuid4()), owner, time.time()))
        return search(query, provider, targets, api_key=key)

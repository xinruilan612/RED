"""Bounded public-web retrieval with DNS pinning and explicit source provenance."""
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit, urlunsplit
from backend.contracts import require, DomainError


def public_url(value):
    require(isinstance(value,str) and 0<len(value)<=2048 and not any(c.isspace() for c in value),'INVALID_INPUT','请输入有效的公开网页链接')
    try:
        p=urlsplit(value)
        require(p.scheme in ('http','https') and p.hostname and not p.username and not p.password and p.port in (None,80,443),'INVALID_INPUT','只允许公开 HTTP/HTTPS 网页，无账号密码或自定义端口')
        host=p.hostname.encode('idna').decode('ascii')
        require(host not in ('localhost','metadata.google.internal') and not host.endswith(('.localhost','.local','.internal')),'FORBIDDEN','不能读取本机或内网地址')
    except (ValueError,UnicodeError) as e:
        if isinstance(e,DomainError): raise
        raise DomainError('INVALID_INPUT','链接格式无效') from None
    netloc=('['+host+']' if ':' in host else host)+((':'+str(p.port)) if p.port else '')
    return urlunsplit((p.scheme,netloc,quote(p.path or '/',safe='/%:@!$&\'()*+,;=-._~'),quote(p.query,safe='=&%/:?@!$\'()*+,;~-._'),''))


def resolve_public(host,port):
    from backend.public_dns import resolve_addresses
    return resolve_addresses(host,port)[0][4][0]


def fetch_public(url, maximum=1_500_000):
    """Resolve once per hop, connect to that IP, validate TLS against original host."""
    for _ in range(4):
        url=public_url(url);p=urlsplit(url)
        from backend.research_access import require_readable_source
        require_readable_source(url)
        port=p.port or (443 if p.scheme=='https' else 80)
        connection=None
        try:
            ip=resolve_public(p.hostname,port)
            from backend.public_dns import configured_proxy, allowed_address
            require(allowed_address(ip),'FORBIDDEN','不能读取本机、内网或保留网络地址')
            proxy=configured_proxy(p.hostname,p.scheme)
            connection=http.client.HTTPConnection(*(proxy or (p.hostname,port)),timeout=8)
            if proxy:
                connection.set_tunnel(ip,port)
                connection.connect()
                sock=connection.sock
            else:
                sock=socket.create_connection((ip,port),timeout=8)
            connection.sock=sock
            if p.scheme=='https':
                context=ssl.create_default_context()
                context.set_alpn_protocols(['http/1.1'])
                sock=context.wrap_socket(sock,server_hostname=p.hostname)
            connection.sock=sock
            connection.request('GET',urlunsplit(('','',p.path or '/',p.query,'')),headers={'Host':p.netloc,'User-Agent':'YoujiResearch/0.6 (+public-source-preview)','Accept':'text/html,application/rss+xml,application/xml,text/xml,text/plain','Accept-Encoding':'identity','Connection':'close'})
            response=connection.getresponse()
            if response.status in (301,302,303,307,308):
                location=response.getheader('Location');require(location,'SOURCE_UNAVAILABLE','来源跳转无效')
                url=urljoin(url,location);continue
            status_code=f'SOURCE_HTTP_{response.status}' if response.status in (403,404,429) else 'SOURCE_HTTP_ERROR'
            require(response.status==200,status_code,f'来源站点返回 HTTP {response.status}，未读取正文；请更换链接或手动粘贴')
            require(response.getheader('Content-Encoding','identity') in ('identity',''),'SOURCE_UNAVAILABLE','来源使用了不支持的压缩格式')
            mime=response.getheader('Content-Type','').lower()
            require(any(t in mime for t in ('text/html','text/plain','xml','rss')),'SOURCE_UNAVAILABLE','首版只读取网页与文本，请使用资料上传导入 PDF')
            body=[];size=0;started=time.monotonic()
            while True:
                block=response.read(8192)
                if not block: break
                body.append(block);size+=len(block)
                require(size<=maximum and time.monotonic()-started<20,'SOURCE_UNAVAILABLE','来源正文过大或读取超时')
            encoding_match=re.search(r'charset=["\']?([\w-]+)',mime)
            encoding=encoding_match[1] if encoding_match else 'utf-8'
            try: text=b''.join(body).decode(encoding,errors='replace')
            except LookupError: raise DomainError('SOURCE_UNAVAILABLE','来源字符编码无效') from None
            return {'url':url,'text':text,'content_type':mime,'fetched_at':datetime.now(timezone.utc).isoformat()}
        except DomainError: raise
        except (OSError,http.client.HTTPException,ValueError):
            raise DomainError('SOURCE_UNAVAILABLE','网络连接或来源读取失败；没有生成替代内容') from None
        finally:
            if connection: connection.close()
    raise DomainError('SOURCE_UNAVAILABLE','来源跳转次数过多')


class Article(HTMLParser):
    excluded={'script','style','nav','header','footer','aside','form','noscript','svg'}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip=[];self.in_title=False;self.title=[];self.parts=[];self.published_at=None

    def handle_starttag(self, tag, attrs):
        if tag in self.excluded: self.skip.append(tag)
        if self.skip: return
        if tag=='title': self.in_title=True
        if tag in ('p','h1','h2','h3','li','br','div'): self.parts.append('\n')
        attrs=dict(attrs)
        if tag=='meta' and attrs.get('property')=='article:published_time':
            value=attrs.get('content','')
            try:
                dt=datetime.fromisoformat(value.replace('Z','+00:00'))
                if dt.tzinfo: self.published_at=dt.isoformat()
            except ValueError: pass

    def handle_endtag(self,tag):
        if self.skip:
            if tag==self.skip[-1]: self.skip.pop()
            return
        if tag=='title': self.in_title=False
        if tag in ('p','div','li'): self.parts.append('\n')

    def handle_data(self,data):
        if self.skip:return
        if self.in_title:self.title.append(data)
        elif data.strip():self.parts.append(data)

    def article(self):
        text='\n'.join(line.strip() for line in ''.join(self.parts).splitlines() if line.strip())
        return {'title':''.join(self.title).strip()[:200] or '网页资料','text':text,'published_at':self.published_at}


def read_article(url, fetch=None):
    url=public_url(url);parsed=urlsplit(url)
    from backend.research_access import require_readable_source
    require_readable_source(url)
    if fetch is None and parsed.scheme=='https' and parsed.netloc=='zh.wikipedia.org' and parsed.path.startswith('/wiki/'):
        response=fetch_search('https://zh.wikipedia.org/w/api.php?'+urlencode(dict(action='query',prop='extracts',explaintext='1',titles=unquote(parsed.path[6:]),format='json',redirects='1')))
        try:
            pages=json.loads(response['text'])['query']['pages']
            page=next(iter(pages.values()))
            result={'title':page['title'][:200],'text':page.get('extract',''),'published_at':None}
        except (ValueError,KeyError,TypeError,StopIteration):
            raise DomainError('SOURCE_UNAVAILABLE','百科正文返回格式无效，请使用其他来源') from None
        response['url']=url
    else:
        response=(fetch or fetch_public)(url)
        if 'html' in response['content_type']:
            parser=Article();parser.feed(response['text']);result=parser.article()
        else: result={'title':'网页文本','text':response['text'],'published_at':None}
    require(40<=len(result['text'])<=100_000,'SOURCE_UNAVAILABLE','没有足够可读取的正文，或正文过长；请手动整理后导入')
    return {**result,'url':response['url'],'fetched_at':response['fetched_at'],'verification':'已读取公开正文，未独立核实事实；时间来自页面声明'}


def fetch_search(url):
    """Fixed search provider; no caller-controlled hosts or redirects.

    The standard HTTPS handler negotiates the provider connection. Arbitrary
    document URLs use fetch_public and its IP-pinned SSRF checks instead.
    """
    from urllib.request import Request, build_opener, HTTPRedirectHandler
    from urllib.error import URLError
    parsed=urlsplit(url)
    require(parsed.scheme=='https' and (parsed.netloc,parsed.path) in (('www.bing.com','/search'),('cn.bing.com','/search'),('zh.wikipedia.org','/w/api.php')),'FORBIDDEN','搜索服务地址无效')
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):
            raise DomainError('SOURCE_UNAVAILABLE','搜索服务要求跳转，已停止')
    try:
        with build_opener(NoRedirect()).open(Request(url,headers={'Accept':'application/json,application/rss+xml,text/xml','User-Agent':'YoujiResearch/0.6 (public-source-preview)','Connection':'close'}),timeout=12) as response:
            data=response.read(500_001)
            require(len(data)<=500_000,'SOURCE_UNAVAILABLE','搜索结果超过大小限制')
            return {'text':data.decode('utf-8'),'fetched_at':datetime.now(timezone.utc).isoformat()}
    except DomainError:raise
    except (URLError,OSError,UnicodeError):
        raise DomainError('SOURCE_UNAVAILABLE','搜索服务暂不可用，没有生成替代结果') from None


def compact_query(query):
    """Remove title/prompt filler, preserving topic words without a paid model."""
    value=query
    if re.search(r'第[一二三四五六七八九十0-9]+步',value):
        value=re.sub(r'(^|\s)新手',r'\1',value)
    value=re.sub(r'第[一二三四五六七八九十0-9]+步|到底|究竟|请问|帮我搜索|帮我查找', ' ', value)
    value=re.sub(r'[，。！？：；、,!?;:]+', ' ', value)
    value=' '.join(value.split())
    return value if len(value)>=2 else query.strip()



_MODEL_SUFFIX = r'(?:Pro|Plus|Ultra|Max|Mini|Air|SE|Slim|Lite|Mark[ -]*[IVX0-9]+)'
_MODEL = re.compile(r'(?<![A-Za-z0-9])([A-Za-z][A-Za-z_-]*[ -]*\d+[A-Za-z0-9]*(?:[ -]+' + _MODEL_SUFFIX + r'){0,3})(?![A-Za-z0-9])', re.I)
# A letter-only product family needs a distinct head plus a known variant.
# Bare words such as Air or Lite cannot establish a product's identity.
_NAMED_MODEL = re.compile(r'(?<![A-Za-z0-9])((?!' + _MODEL_SUFFIX + r'(?:[ -]|$))[A-Za-z]+(?:[ -]+' + _MODEL_SUFFIX + r'){1,3})(?![A-Za-z0-9])', re.I)


def model_terms(text):
    """Spacing/hyphens are formatting; different model suffixes are not aliases."""
    matches = sorted(list(_MODEL.finditer(text)) + list(_NAMED_MODEL.finditer(text)), key=lambda match: match.start())
    return list(dict.fromkeys(match.group(1) for match in matches))


def topic_match(query, text):
    from backend.knowledge import tokens
    normalize = lambda value: re.sub(r'[^a-z0-9]', '', value.lower())
    models = {normalize(item) for item in model_terms(query)}
    if models and not models.issubset({normalize(item) for item in model_terms(text)}):
        return False
    wanted = set(tokens(query))
    matched = wanted & set(tokens(text))
    return bool(models or (matched and (len(wanted) <= 5 or len(matched) >= 2)))



def related_model_match(query, text):
    """Same model stem and generation is a lead, never proof of variant equivalence."""
    def family(value):
        match=re.match(r'([a-z]+)(\d+)',re.sub(r'[^a-z0-9]','',value.lower()))
        return match.groups() if match else None
    requested={family(value) for value in model_terms(query)}-{None}
    observed={family(value) for value in model_terms(text)}-{None}
    return bool(requested and requested & observed)

def official_priority(row):
    """Ranking hint only, never a certification that a publisher is official."""
    host = (urlsplit(row.get('url', '')).hostname or '').lower()
    title = row.get('title', '').lower()
    root = host.split('.')[-2] if '.' in host else host
    public_institution = host.endswith(('.gov', '.gov.cn', '.edu', '.edu.cn'))
    branded = len(root) > 2 and bool(re.search(r'(?<![a-z0-9])' + re.escape(root) + r'(?![a-z0-9])', title))
    return 2 if public_institution else 1 if branded and ('官方' in title or '官网' in title or 'official' in title or ' - ' in title or '技术参数' in title or '商城' in title or 'store' in title) else 0


def _bing_results(response, query):
    try:
        root = ET.fromstring(response['text'])
    except ET.ParseError:
        raise DomainError('SOURCE_UNAVAILABLE', '搜索源返回格式变化，请稍后再试') from None
    require(root.tag=='rss' and root.find('./channel') is not None, 'SOURCE_UNAVAILABLE', '搜索服务未返回有效RSS结果，不能视为没有相关资料')
    results, related, seen, excluded = [], [], set(), 0
    for node in root.findall('./channel/item'):
        try:
            url = public_url(node.findtext('link') or '')
        except DomainError:
            continue
        if url in seen:
            continue
        seen.add(url)
        clean = lambda value: unescape(re.sub('<[^>]+>', '', value or '')).strip()
        title = clean(node.findtext('title'))[:200]
        snippet = clean(node.findtext('description'))[:600]
        row = {'title': title, 'url': url, 'snippet': snippet,
               'fetched_at': response['fetched_at'], 'published_at': None,
               'body_read': False, 'source_type': 'search_result'}
        row['authority_hint'] = 'official_candidate' if official_priority(row) else 'unverified_publisher'
        if not topic_match(query, title + ' ' + snippet):
            if related_model_match(query,title+' '+snippet):
                related.append({**row,'model_match':'related_unconfirmed'})
            else:excluded += 1
            continue
        results.append(row)
    return (sorted(results, key=official_priority, reverse=True)[:8], excluded,
            sorted(related,key=official_priority,reverse=True)[:4])

def search_web(query, fetch=None, provider='bing'):
    require(isinstance(query,str) and 2<=len(query.strip())<=120,'INVALID_INPUT','搜索词需为 2 至 120 个字符')
    require(provider in ('bing','wikipedia'),'INVALID_INPUT','搜索来源无效')
    if provider=='wikipedia':
        response=(fetch or fetch_search)('https://zh.wikipedia.org/w/api.php?'+urlencode(dict(action='query',list='search',srsearch=query.strip(),format='json',srlimit=8)))
        try:
            rows=json.loads(response['text'])['query']['search']
            results=[{'title':r['title'][:200],'url':'https://zh.wikipedia.org/wiki/'+quote(r['title']),
                      'snippet':unescape(re.sub('<[^>]+>','',r['snippet']))[:600],
                      'fetched_at':response['fetched_at'],'published_at':None,'body_read':False,'source_type':'search_result'} for r in rows[:8]]
        except (ValueError,KeyError,TypeError):
            raise DomainError('SOURCE_UNAVAILABLE','百科搜索返回格式变化，请稍后再试') from None
        return {'query':query,'provider':'维基百科公开 API · 背景知识','searched_at':response['fetched_at'],'results':results,
                'note':'用于查找背景知识，不代表最新新闻或平台热度。摘要需读取正文后才能进入资料证据；百科内容仍需核实。'}
    effective_query=compact_query(query)
    transport=fetch or fetch_search
    response=transport('https://cn.bing.com/search?'+urlencode({'q':effective_query,'format':'rss'}))
    results,excluded,related=_bing_results(response,effective_query)
    attempts=[{'query':effective_query,'status':'ok','matched_results':len(results),'excluded_unrelated':excluded}]
    # RSS sometimes ignores the rest of a mixed-language query. One bounded,
    # phrase-preserving fallback helps without asserting anything about release status.
    models=model_terms(effective_query)
    if not results and models:
        first=_MODEL.search(effective_query)
        prefix=effective_query[:first.start()].strip(' \"') if first else ''
        prefix=re.sub(r'请问|帮我|搜索|查找|介绍|参数|官方|官网', '', prefix).strip()
        phrases=[re.sub(r'(\d)([A-Za-z])',r'\1 \2',re.sub(r'([A-Za-z])(\d)',r'\1 \2',model.replace('-',' '))) for model in models]
        precise=' '.join('"'+part+'"' for part in ([prefix] if prefix else [])+phrases)
        if precise!=effective_query:
            try:
                fallback=transport('https://cn.bing.com/search?'+urlencode({'q':precise,'format':'rss'}))
                results,removed,extra_related=_bing_results(fallback,effective_query)
                known_related={row['url'] for row in related}
                related.extend(row for row in extra_related if row['url'] not in known_related)
                excluded+=removed;response=fallback
                attempts.append({'query':precise,'status':'ok','matched_results':len(results),'excluded_unrelated':removed})
            except DomainError as error:
                attempts.append({'query':precise,'status':'failed','error':str(error)})
    return {'query':query,'provider':'Bing 中文公开 RSS 搜索（实验接入）','effective_query':effective_query,
            'searched_at':response['fetched_at'],'results':results,'related_results':related[:4],'attempts':attempts,
            'search_status':'complete' if all(a['status']=='ok' for a in attempts) else 'partial_failure',
            'excluded_unrelated':excluded,
            'note':f'搜索摘要尚未读取正文；已排除 {excluded} 条主题或型号不匹配结果。无结果只表示本次未查到，不能推断产品未发布或事实不存在。官方标识仅作排序线索，仍须核对正文和发布主体。'}

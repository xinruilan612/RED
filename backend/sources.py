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
    return urlunsplit((p.scheme,p.netloc,p.path or '/',p.query,''))


def resolve_public(host,port):
    addresses=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
    require(addresses,'SOURCE_UNAVAILABLE','无法解析来源地址')
    for result in addresses:
        ip=ipaddress.ip_address(result[4][0])
        require(ip.is_global and not ip.is_multicast and not getattr(ip,'ipv4_mapped',None) and not getattr(ip,'sixtofour',None),'FORBIDDEN','不能读取本机、内网或保留网络地址')
    return addresses[0][4][0]


def fetch_public(url, maximum=1_500_000):
    """Resolve once per hop, connect to that IP, validate TLS against original host."""
    for _ in range(4):
        url=public_url(url);p=urlsplit(url)
        port=p.port or (443 if p.scheme=='https' else 80)
        connection=None
        try:
            ip=resolve_public(p.hostname,port)
            connection=http.client.HTTPConnection(p.hostname,port,timeout=8)
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
            require(response.status==200,'SOURCE_UNAVAILABLE','来源未返回可读取内容，请更换链接或手动粘贴')
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
    require(parsed.scheme=='https' and (parsed.netloc,parsed.path) in (('www.bing.com','/search'),('zh.wikipedia.org','/w/api.php')),'FORBIDDEN','搜索服务地址无效')
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
    response=(fetch or fetch_search)('https://www.bing.com/search?format=rss&q='+quote(query.strip()))
    try: root=ET.fromstring(response['text'])
    except ET.ParseError: raise DomainError('SOURCE_UNAVAILABLE','搜索源返回格式变化，请稍后再试') from None
    from backend.knowledge import tokens
    wanted=set(tokens(query))
    results=[];seen=set();excluded=0
    for node in root.findall('./channel/item'):
        url=node.findtext('link') or ''
        try: url=public_url(url)
        except DomainError:continue
        if url in seen:continue
        seen.add(url)
        clean=lambda value:unescape(re.sub('<[^>]+>','',value or '')).strip()
        title=clean(node.findtext('title'))[:200];snippet=clean(node.findtext('description'))[:600]
        matched=wanted & set(tokens(title+' '+snippet))
        if not matched or (len(wanted)>5 and len(matched)<2):
            excluded+=1;continue
        results.append({'title':title,'url':url,'snippet':snippet,
                        'fetched_at':response['fetched_at'],'published_at':None,'body_read':False,'source_type':'search_result'})
        if len(results)==8:break
    return {'query':query,'provider':'Bing 公开 RSS 搜索（实验接入）','searched_at':response['fetched_at'],'results':results,
            'excluded_unrelated':excluded,
            'note':f'只返回搜索摘要，不代表实时热榜；已隐藏 {excluded} 条无关键词匹配的结果。需读取正文后才能进入资料证据。公开渠道可能限流或无相关结果。'}

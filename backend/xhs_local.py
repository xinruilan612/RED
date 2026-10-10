"""Bounded read-only xiaohongshu-mcp client. Never expose cookies or write tools."""
import json
import http.client
import queue
import socket
import threading
import time
import base64
import struct
import zlib
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from backend.contracts import DomainError, require


def http_failure(exc, prefix='XHS'):
    """Classify fixed connector signals; never echo its ticket-bearing body."""
    status=exc.code if type(exc.code) is int and 100<=exc.code<=599 else None
    try:
        raw=exc.read(65537)
        value=json.loads(raw) if len(raw)<=65536 else {}
        signal=' '.join(str(value.get(k,'')) for k in ('code','error','message','details')).lower() if isinstance(value,dict) else ''
    except Exception:signal=''
    finally:exc.close()
    def tagged(code,message):
        error=DomainError(code,message)
        error.error_origin='mcp_http'
        error.mcp_http_status=status
        return error
    if any(term in signal for term in ('context deadline exceeded','timed out','timeout')):
        return tagged(prefix+'_TIMEOUT','平台读取超时；已取得候选保留，可稍后手动重试')
    if any(term in signal for term in ('login_required','not_logged_in','登录已失效','未登录')):
        return tagged('XHS_LOGIN_REQUIRED','连接器登录会话失效，请点击重新连接')
    if status==429 or any(term in signal for term in ('captcha','验证码','access_restricted')):
        return tagged('XHS_RESTRICTED','平台要求访问验证或限制访问；本次停止，不自动重试')
    if any(term in signal for term in ('parse_error','json decode','invalid character')):
        return tagged('XHS_PARSE','平台响应解析失败；不表示登录失效')
    if any(term in signal for term in ('selector not found','element not found','页面结构')):
        return tagged('XHS_STRUCTURE','平台页面结构无法识别；不表示登录失效')
    return tagged(prefix+'_HTTP_'+str(status) if status is not None else prefix+'_HTTP_ERROR',
                       '本机接口返回错误状态；原因未确定，本次不自动重试')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DomainError('XHS_TRANSPORT', '本机连接器不允许重定向')


REQUEST_TIMEOUT_SECONDS=65


class LocalXHS:
    def __init__(self, port=18061, token_file='runtime/xhs-local/control-token'):
        require(type(port) is int and 1024<=port<=65535,'INVALID_INPUT','本机连接器端口无效')
        self.base='http://127.0.0.1:'+str(port)
        self.token_file=Path(token_file)
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())

    def read_response(self, req):
        """Cancel only this request's socket; never touch the shared browser/session.

        The connector sees client disconnect. Its own browser work also needs to
        honor HTTP context cancellation; we never relaunch or retry it here.
        """
        guard=getattr(self,'check',None)
        if guard is None:
            with self.opener.open(req,timeout=REQUEST_TIMEOUT_SECONDS) as response:return response.read(8_000_001)
        from urllib.parse import urlsplit
        parsed=urlsplit(req.full_url)
        request_deadline=min(time.monotonic()+REQUEST_TIMEOUT_SECONDS,getattr(self,'deadline',float('inf')))
        connection=http.client.HTTPConnection(parsed.hostname,parsed.port,timeout=REQUEST_TIMEOUT_SECONDS)
        result=queue.Queue(maxsize=1)
        sockets=[]
        cancelled=threading.Event()
        def run():
            try:
                connection.connect()
                sockets.append(connection.sock)
                if cancelled.is_set():return
                connection.request(req.get_method(),parsed.path,body=req.data,headers=dict(req.header_items()))
                response=connection.getresponse()
                if 300<=response.status<400:raise DomainError('XHS_TRANSPORT','本机连接器不允许重定向')
                if response.status>=400:
                    import io
                    raise urllib.error.HTTPError(req.full_url,response.status,'Local connector error',{},io.BytesIO(response.read(65537)))
                result.put((True,response.read(8_000_001)))
            except Exception as exc:result.put((False,exc))
            finally:connection.close()
        guard()
        threading.Thread(target=run,daemon=True,name='xhs-project-read').start()
        try:
            while True:
                guard()
                if time.monotonic()>=request_deadline:
                    error=DomainError('XHS_TIMEOUT','连接器请求达到绝对时限；停止该请求')
                    error.error_origin='client_deadline'
                    error.mcp_http_status=None
                    raise error
                try:success,value=result.get(timeout=0.25)
                except queue.Empty:continue
                guard()
                if success:return value
                raise value
        except BaseException:
            cancelled.set()
            for active_socket in sockets:
                try:active_socket.shutdown(socket.SHUT_RDWR)
                except OSError:pass
            connection.close()
            raise

    def request(self,path,data=None):
        allowed={'/api/v1/login/status','/api/v1/login/qrcode','/api/v1/user/me','/api/v1/feeds/detail'}
        require(path in allowed,'FORBIDDEN','同步器只允许身份、本人笔记和详情读取')
        require(path!='/api/v1/login/qrcode' or data is None,'FORBIDDEN','登录二维码仅允许固定 GET 请求')
        try:
            token=self.token_file.read_text().strip()
            req=urllib.request.Request(self.base+path,data=None if data is None else json.dumps(data).encode(),
                    headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
            body=self.read_response(req)
            require(len(body)<=8_000_000,'XHS_RESPONSE','连接器响应过大')
            value=json.loads(body)
            require(isinstance(value,dict) and value.get('success') is True and isinstance(value.get('data'),dict),
                    'XHS_PARSE','连接器响应结构异常；不能据此判断登录失效')
            return value['data']
        except DomainError:raise
        except urllib.error.HTTPError as exc:
            raise http_failure(exc) from None
        except TimeoutError:
            raise DomainError('XHS_TIMEOUT','笔记读取超时；未自动重试，已取得结果保留') from None
        except urllib.error.URLError as exc:
            code='XHS_TIMEOUT' if isinstance(exc.reason,TimeoutError) else 'XHS_CONNECTION'
            raise DomainError(code,'本机连接器连接失败；请检查服务状态') from None
        except (ConnectionError,OSError):
            raise DomainError('XHS_CONNECTION','本机连接器连接不可用；请检查服务状态') from None
        except (ValueError,TypeError,AttributeError):
            raise DomainError('XHS_PARSE','本机连接器响应解析失败；不表示登录失效') from None
        except Exception:raise DomainError('XHS_TRANSPORT','本机连接器读取失败；未自动重试') from None

    def identity(self):
        result=self.request('/api/v1/login/status')
        require(result.get('is_logged_in') is True,'XHS_LOGIN_REQUIRED','小红书登录已失效，请本人重新登录')
        require(isinstance(result.get('user_id'),str) and result['user_id'],
                'XHS_IDENTITY_UNVERIFIED','已登录但无法核实账号ID，暂停同步')
        return {'id':result['user_id'],'nickname':str(result.get('username') or '')[:200]}

    def reconnect(self):
        result=self.request('/api/v1/login/qrcode')
        if result.get('is_logged_in') is True:
            return {'is_logged_in':True,'img':None,'timeout':None}
        value=result.get('img');prefix='data:image/png;base64,'
        require(isinstance(value,str) and value.startswith(prefix) and len(value)<=750000,'XHS_RESPONSE','二维码必须为受限大小的 PNG 图片')
        try:
            raw=base64.b64decode(value[len(prefix):],validate=True)
            require(raw.startswith(b'\x89PNG\r\n\x1a\n'),'XHS_RESPONSE','二维码图片格式无效')
            position=8;chunks=[]
            while position<len(raw):
                size=struct.unpack('>I',raw[position:position+4])[0]
                require(size<=500000 and position+12+size<=len(raw),'XHS_RESPONSE','二维码图片结构无效')
                kind=raw[position+4:position+8];payload=raw[position+8:position+8+size]
                crc=struct.unpack('>I',raw[position+8+size:position+12+size])[0]
                require(zlib.crc32(kind+payload)==crc,'XHS_RESPONSE','二维码图片校验失败')
                if not chunks:
                    require(kind==b'IHDR' and size==13,'XHS_RESPONSE','二维码图片头无效')
                    width,height=struct.unpack('>II',payload[:8])
                    require(0<width<=2048 and 0<height<=2048,'XHS_RESPONSE','二维码图片尺寸超限')
                chunks.append(kind);position+=12+size
            require(chunks[-1:]==[b'IEND'] and b'IDAT' in chunks,'XHS_RESPONSE','二维码图片不完整')
        except DomainError:raise
        except (ValueError,struct.error):raise DomainError('XHS_RESPONSE','二维码图片编码无效') from None
        timeout=result.get('timeout')
        require(isinstance(timeout,(str,int)) and not isinstance(timeout,bool) and len(str(timeout))<=40 and re.fullmatch(r'(?:[0-9]+(?:\.[0-9]+)?(?:ms|s|m|h)?){1,4}',str(timeout)),'XHS_RESPONSE','二维码有效期无效')
        return {'is_logged_in':False,'img':value,'timeout':timeout}

    def collect(self,expected_id,limit=5,check=lambda:None):
        require(type(limit) is int and 1<=limit<=5,'INVALID_INPUT','每轮最多读取5篇笔记')
        check();identity=self.identity()
        require(identity['id']==expected_id,'XHS_IDENTITY_CHANGED','MCP当前账号与绑定账号不同，暂停同步')
        check();profile=self.request('/api/v1/user/me');profile=profile.get('data',profile)
        feeds=profile.get('feeds')
        require(isinstance(feeds,list),'XHS_RESPONSE','本人笔记列表格式异常')
        records=[];failures=[];seen=set()
        for feed in feeds:
            if len(seen)>=limit:break
            note_id=feed.get('id');token=feed.get('xsecToken')
            if not isinstance(note_id,str) or not note_id or note_id in seen:continue
            seen.add(note_id)
            if not isinstance(token,str) or not token:
                failures.append({'note_id':note_id,'reason':'MISSING_SOURCE_TOKEN'});continue
            check()
            try:
                response=self.request('/api/v1/feeds/detail',{'feed_id':note_id,'xsec_token':token,'load_all_comments':False})
                record=normalize_detail(response.get('data',response),expected_id,note_id)
                records.append(record)
            except DomainError as exc:
                if exc.code in ('XHS_IDENTITY_CHANGED','XHS_STOPPED'):raise
                failures.append({'note_id':note_id,'reason':exc.code})
        check();after=self.identity()
        require(after['id']==expected_id,'XHS_IDENTITY_CHANGED','采集期间账号发生变化，本轮不保存')
        from backend.creator_reader import collect_creator
        check();creator_metrics=collect_creator(expected_id);check()
        require(self.identity()['id']==expected_id,'XHS_IDENTITY_CHANGED','创作者页面读取期间账号发生变化，本轮不保存')
        return {'identity':identity,'notes':records,'failures':failures,'listed_notes':len(feeds),
                'creator_metrics':creator_metrics,
                'observed_at':datetime.now(timezone.utc).isoformat(),
                'coverage':'仅本轮主页返回的前5篇笔记及已加载评论，非全量历史或全部评论',
                'source_method':'local_browser_mcp','official_api':False,'source_updated_at':None}


def number(value):
    """Keep rounded display counts unknown instead of inventing exact metrics."""
    if type(value) is int:return value if value>=0 else None
    if isinstance(value,str) and re.fullmatch(r'[0-9]+',value.strip()):return int(value.strip())
    return None


def normalize_detail(data,expected_id,note_id):
    require(isinstance(data,dict) and isinstance(data.get('note'),dict),'XHS_RESPONSE','笔记详情格式异常')
    note=data['note'];require(note.get('noteId')==note_id,'XHS_RESPONSE','返回笔记ID不一致')
    require(note.get('user',{}).get('userId')==expected_id,'XHS_IDENTITY_CHANGED','笔记作者不是绑定账号')
    info=note.get('interactInfo') or {}
    metrics={key:number(info.get(raw)) for key,raw in [('likes','likedCount'),('favorites','collectedCount'),('comments','commentCount'),('shares','sharedCount')]}
    metrics.update(views=None,exposure=None)
    comments=[];seen=set()
    def collect(items,parent=None):
        for item in items if isinstance(items,list) else []:
            if len(comments)>=100:return
            if not isinstance(item,dict):continue
            identity=item.get('id')
            if not isinstance(identity,str) or not identity or identity in seen:continue
            seen.add(identity)
            comments.append({'id':identity,'parent_id':parent,'content':str(item.get('content') or '')[:8000],
                             'created_at':item.get('createTime') if type(item.get('createTime')) is int else None,
                             'likes':number(item.get('likeCount'))})
            collect(item.get('subComments'),identity)
    source_comments=data.get('comments') or {};collect(source_comments.get('list'))
    return {'id':note_id,'title':str(note.get('title') or '')[:500],'text':str(note.get('desc') or '')[:100000],
            'author_id':expected_id,'published_at':note.get('time') if type(note.get('time')) is int else None,
            'url':'https://www.xiaohongshu.com/explore/'+note_id,'metrics':metrics,'comments':comments,
            'comments_partial':True,'comments_has_more':source_comments.get('hasMore'),
            'source_updated_at':None,'metric_display':{key:str(info.get(key) or '')[:30] for key in
            ('likedCount','collectedCount','commentCount','sharedCount')}}

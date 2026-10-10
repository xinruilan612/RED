"""Bounded read-only xiaohongshu-mcp client. Never expose cookies or write tools."""
import json
import base64
import struct
import zlib
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from backend.contracts import DomainError, require


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DomainError('XHS_TRANSPORT', '本机连接器不允许重定向')


class LocalXHS:
    def __init__(self, port=18061, token_file='runtime/xhs-local/control-token'):
        require(type(port) is int and 1024<=port<=65535,'INVALID_INPUT','本机连接器端口无效')
        self.base='http://127.0.0.1:'+str(port)
        self.token_file=Path(token_file)
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())

    def request(self,path,data=None):
        allowed={'/api/v1/login/status','/api/v1/login/qrcode','/api/v1/user/me','/api/v1/feeds/detail'}
        require(path in allowed,'FORBIDDEN','同步器只允许身份、本人笔记和详情读取')
        require(path!='/api/v1/login/qrcode' or data is None,'FORBIDDEN','登录二维码仅允许固定 GET 请求')
        try:
            token=self.token_file.read_text().strip()
            req=urllib.request.Request(self.base+path,data=None if data is None else json.dumps(data).encode(),
                    headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
            with self.opener.open(req,timeout=85) as response:
                body=response.read(8_000_001)
            require(len(body)<=8_000_000,'XHS_RESPONSE','连接器响应过大')
            value=json.loads(body)
            require(value.get('success') is True and isinstance(value.get('data'),dict),
                    'XHS_RESPONSE','连接器未返回有效资料；请查看本机连接状态')
            return value['data']
        except DomainError:raise
        except Exception:raise DomainError('XHS_TRANSPORT','本机连接器不可用或返回异常；未保存本轮结果') from None

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
        return {'identity':identity,'notes':records,'failures':failures,'listed_notes':len(feeds),
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

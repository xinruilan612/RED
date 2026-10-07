"""Explicit, bounded public-reference collection. Never personal outcome labels."""
import copy
import json
import math
import os
import re
import urllib.request
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path
from backend.accounts import find_account
from backend.contracts import DomainError, require
from backend.demo import validate_text

SORTS=('综合','最新','最多点赞')
CONNECTOR_DIR=Path(__file__).resolve().parents[1]/'runtime'/'xhs'

def now(): return datetime.now(timezone.utc).isoformat()

def count(value):
    if type(value) is int: return value if 0<=value<=10**12 else None
    if isinstance(value,str) and len(value)<=32:
        match=re.fullmatch(r'(\d+(?:\.\d+)?)([万wW千kK]?)',value.strip().replace(',',''))
        if match:
            number=float(match[1])*({'万':10000,'w':10000,'W':10000,'千':1000,'k':1000,'K':1000}.get(match[2],1))
            if math.isfinite(number) and 0<=number<=10**12: return int(number)
    return None

def text(value,limit): return value[:limit] if isinstance(value,str) else ''

def detail_card(result,identity):
    # PublicClient already unwraps the outer success/data envelope. The official
    # detail payload is {feed_id, data: {note, comments}}; no comments are retained.
    require(isinstance(result,dict),'PUBLIC_SOURCE_UNAVAILABLE','笔记详情暂不可读，保留已有参考')
    detail=result.get('data',result)
    require(isinstance(detail,dict) and isinstance(detail.get('note'),dict),'PUBLIC_SOURCE_UNAVAILABLE','笔记详情暂不可读，保留已有参考')
    note=detail['note'];returned=note.get('noteId',note.get('note_id',identity))
    require(returned==identity,'PUBLIC_SOURCE_UNAVAILABLE','笔记详情与请求不一致，保留已有参考')
    require(any(isinstance(note.get(k),str) and note[k].strip() for k in ('title','desc')),'PUBLIC_SOURCE_UNAVAILABLE','笔记内容暂不可读，保留已有参考')
    return note

def note_id(url):
    require(isinstance(url,str) and len(url)<=4000,'INVALID_INPUT','公开链接格式无效')
    match=re.fullmatch(r'https://(?:www\.)?xiaohongshu\.com/(?:explore|discovery/item)/([a-zA-Z0-9_-]{8,80})(?:\?[^\s]*)?',url)
    require(match,'INVALID_INPUT','请填写小红书笔记的完整公开链接')
    return match[1]

def normalize(row,source,keyword='',sort=''):
    require(isinstance(row,dict),'INVALID_INPUT','参考样本格式无效')
    card=row.get('noteCard',row.get('note_card',row))
    require(isinstance(card,dict),'INVALID_INPUT','参考卡片格式无效')
    identity=row.get('id') or row.get('note_id') or card.get('note_id')
    url=row.get('url') or ('https://www.xiaohongshu.com/explore/'+str(identity))
    identity=note_id(url)
    raw=card.get('interactInfo',card.get('interact_info',card.get('counts',{}))) or {}
    if not isinstance(raw,dict): raw={}
    aliases={'likes':('likes','likedCount','liked_count'),'saves':('saves','collectedCount','collected_count'),'comments':('comments','commentCount','comment_count'),'shares':('shares','sharedCount','shareCount','share_count','shared_count'),'views':('views','viewCount','view_count')}
    counts={k:next((count(raw[x]) for x in names if x in raw),None) for k,names in aliases.items()}
    images=card.get('image_urls',card.get('imageList',card.get('image_list',[]))) or []
    if not isinstance(images,list): images=[]
    cover=card.get('cover')
    if not images and isinstance(cover,dict): images=[cover]
    urls=[]
    for item in images[:9]:
        if not isinstance(item,(str,dict)): continue
        u=item if isinstance(item,str) else item.get('urlDefault',item.get('url_default',item.get('url','')))
        if isinstance(u,str) and u.startswith('https://') and len(u)<=2000: urls.append(u)
    user=card.get('user',{}) or {}
    if not isinstance(user,dict): user={}
    published=card.get('published_at') or card.get('time') or None
    if type(published) in (int,float):
        try: published=datetime.fromtimestamp(published/(1000 if published>1e11 else 1),timezone.utc).isoformat()
        except (ValueError,OverflowError,OSError): published=None
    if published:
        try:
            date=datetime.fromisoformat(str(published).replace('Z','+00:00'))
            published=date.isoformat() if date.tzinfo and date<=datetime.now(timezone.utc) else None
        except ValueError: published=None
    stamp=now()
    return dict(id=identity,url='https://www.xiaohongshu.com/explore/'+identity,title=text(card.get('displayTitle',card.get('title','')),300),body=text(card.get('desc',card.get('body','')),12000),content_status='detail_read' if source=='public_detail' else ('manual_supplied' if source=='manual_public' else 'search_summary'),author=text(card.get('author') or user.get('nickname',''),200),author_id=text(user.get('userId',user.get('user_id','')),100),image_urls=urls,published_at=published,observed_at=stamp,counts=counts,observations=[dict(observed_at=stamp,counts=counts)],source=source,keyword=keyword,search_sorts=[sort] if sort else [],xsec_token=text(row.get('xsecToken',row.get('xsec_token','')),2000),prediction_eligible=False,exclusion='公开累计互动，不是本账号固定时长结果')

class PublicClient:
    """No user-controlled server URL, redirects, proxies, or mutation endpoints."""
    def request(self,path,data=None):
        require(path in ('/feeds/search','/feeds/detail','/login/status','/login/qrcode'),'INVALID_INPUT','仅支持公开检索与登录检查')
        headers={'Content-Type':'application/json'}
        token=os.environ.get('YOUJI_XHS_TOKEN','')
        if not token:
            try: token=(CONNECTOR_DIR/'auth-token').read_text().strip()
            except OSError: pass
        if token: headers['Authorization']='Bearer '+token
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs): return None
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        request=urllib.request.Request('http://127.0.0.1:18060/api/v1'+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
        try:
            with opener.open(request,timeout=15) as response:
                raw=response.read(3_000_001)
            if len(raw)>3_000_000: raise ValueError('oversized')
            result=json.loads(raw)
            if not isinstance(result,dict) or result.get('success') is False: raise ValueError('source rejected request')
            return result.get('data',result)
        except Exception as exc:
            raise DomainError('PUBLIC_SOURCE_UNAVAILABLE','公开搜索暂不可用，请检查本机连接和小红书登录；也可以手工添加参考') from exc
    def search(self,keyword,sort): return self.request('/feeds/search',dict(keyword=keyword,filters={'sort_by':sort}))
    def detail(self,identity,token): return self.request('/feeds/detail',dict(feed_id=identity,xsec_token=token,load_all_comments=False))
    def status(self): return self.request('/login/status')
    def qrcode(self): return self.request('/login/qrcode')

def merge_samples(previous,incoming):
    result=copy.deepcopy(previous)
    for row in incoming:
        old=next((x for x in result if x['id']==row['id']),None)
        if old:
            observations=(old.get('observations',[])+row['observations'])[-30:]
            sorts=list(dict.fromkeys(old.get('search_sorts',[])+row.get('search_sorts',[])))
            # Search cards can omit body/date/images; do not erase richer detail.
            if old.get('content_status')=='detail_read' and row.get('content_status')=='search_summary':
                row['body']=old.get('body','');row['content_status']='detail_read'
            row={**old,**{k:v for k,v in row.items() if v not in ('',None,[])}}
            row.update(observations=observations,search_sorts=sorts)
            result[result.index(old)]=row
        else: result.append(row)
    return result[-200:]

def public_response(value):
    """Remove connector-only access fields from API responses, including nested state.

    Work on new containers so refresh operations retain server-side source tokens.
    """
    if isinstance(value,dict): return {k:public_response(v) for k,v in value.items() if k not in ('xsec_token','xsecToken')}
    if isinstance(value,list): return [public_response(v) for v in value]
    return value

def apply_public_topic_action(state,action,data):
    require(action=='public_topics_update' and set(data)=={'account_id','samples'},'INVALID_INPUT','公开参考参数无效')
    account=find_account(state,data['account_id'])
    state.setdefault('public_topic_samples',{})[account['id']]=copy.deepcopy(data['samples'])
    state.setdefault('topic_results',{}).pop(account['id'],None)

class PublicTopics:
    def __init__(self,operations,client=None): self.operations=operations;self.client=client or PublicClient()
    def check_connector_owner(self,owner):
        if not isinstance(self.client,PublicClient): return
        try: configured=(CONNECTOR_DIR/'owner-id').read_text().strip()
        except OSError: configured=''
        require(bool(configured) and configured==owner,'PUBLIC_SOURCE_UNAVAILABLE','此网站账号未连接本机小红书；仍可手工添加公开参考')
    def current(self,owner,identity,version=None):
        state=self.operations.read(owner);account=find_account(state,identity)
        require(not account.get('demo_sample'),'INVALID_INPUT','请使用自己的账号保存公开参考')
        require(account['platform']=='xiaohongshu','INVALID_INPUT','当前公开检索支持小红书账号')
        if version is not None: require(type(version) is int and state['version']==version,'VERSION_CONFLICT','数据已更新，请刷新后重试')
        return state,account
    def read(self,owner,identity):
        state,account=self.current(owner,identity)
        samples=copy.deepcopy(state.get('public_topic_samples',{}).get(identity,[]))
        for row in samples: row.pop('xsec_token',None)
        return dict(account_id=identity,version=state['version'],samples=samples,source='public_reference',prediction_ready=False,connection='not_checked')
    def save(self,owner,data,samples):
        self.current(owner,data['account_id'],data['version'])
        self.operations.command(owner,dict(action='public_topics_update',payload=dict(account_id=data['account_id'],samples=samples),version=data['version'],key=str(uuid4())),internal=True)
        return self.read(owner,data['account_id'])
    def search(self,owner,data):
        require(set(data)=={'account_id','version','keyword'},'INVALID_INPUT','搜索参数无效')
        state,_=self.current(owner,data['account_id'],data['version']);self.check_connector_owner(owner);keyword=validate_text(data['keyword'],'搜索词',100)
        incoming=[];warnings=[]
        for sort in SORTS:
            try: result=self.client.search(keyword,sort)
            except DomainError:
                if not incoming: raise
                warnings.append('部分排序未完成，已保留取得的公开样本');break
            rows=result.get('feeds',result.get('items',[])) if isinstance(result,dict) else []
            if not isinstance(rows,list):
                warnings.append('公开搜索返回格式不完整，已保留原有参考');continue
            for row in rows[:8]:
                try: incoming.append(normalize(row,'public_search',keyword,sort))
                except (DomainError,TypeError,AttributeError): continue
        result=self.save(owner,data,merge_samples(state.get('public_topic_samples',{}).get(data['account_id'],[]),incoming))
        result.update(warnings=warnings,added=len({r['id'] for r in incoming}));return result
    def import_samples(self,owner,data):
        require(set(data)=={'account_id','version','samples'},'INVALID_INPUT','导入参数无效')
        state,_=self.current(owner,data['account_id'],data['version'])
        require(isinstance(data['samples'],list) and 1<=len(data['samples'])<=20,'INVALID_INPUT','每次添加 1 至 20 条公开参考')
        incoming=[normalize(row,'manual_public') for row in data['samples']]
        return self.save(owner,data,merge_samples(state.get('public_topic_samples',{}).get(data['account_id'],[]),incoming))
    def refresh(self,owner,data):
        require(set(data)=={'account_id','version','sample_id'},'INVALID_INPUT','更新参数无效')
        state,_=self.current(owner,data['account_id'],data['version']);samples=state.get('public_topic_samples',{}).get(data['account_id'],[])
        old=next((r for r in samples if r['id']==data['sample_id']),None)
        require(old,'RESOURCE_NOT_FOUND','找不到此账号的参考')
        self.check_connector_owner(owner)
        result=self.client.detail(old['id'],old.get('xsec_token',''))
        detail=detail_card(result,old['id'])
        row=normalize(dict(id=old['id'],xsec_token=old.get('xsec_token',''),noteCard=detail),'public_detail',old.get('keyword',''))
        return self.save(owner,data,merge_samples(samples,[row]))
    def remove(self,owner,data):
        require(set(data)=={'account_id','version','sample_id'},'INVALID_INPUT','删除参数无效')
        state,_=self.current(owner,data['account_id'],data['version']);samples=state.get('public_topic_samples',{}).get(data['account_id'],[])
        require(any(r['id']==data['sample_id'] for r in samples),'RESOURCE_NOT_FOUND','找不到此账号的参考')
        return self.save(owner,data,[r for r in samples if r['id']!=data['sample_id']])
    def connect(self,owner,data):
        require(set(data)=={'account_id','mode'} and data['mode'] in ('status','qrcode'),'INVALID_INPUT','连接参数无效')
        self.current(owner,data['account_id']);self.check_connector_owner(owner)
        return self.client.status() if data['mode']=='status' else self.client.qrcode()

"""Explicit, bounded local-account public-note research; no write operations.

Public note access parameters are retained in original links; connector credentials are never exposed. Video descriptions are text evidence,
never claimed to be a watched video or a transcript.
"""
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlencode
from backend.contracts import DomainError, require
from backend.xhs_local import LocalXHS, number, http_failure


TASK_TIMEOUT_SECONDS=180
RETRY_DELAY_SECONDS=3
METRIC_FIELDS=(('likes','likedCount'),('favorites','collectedCount'),('comments','commentCount'),('shares','sharedCount'))

class XHSResearch:
    def __init__(self, store, client_factory=None):
        self.store = store
        self.factory = client_factory or LocalResearchClient

    def connection(self, owner, account_id):
        with self.store.connect() as db:
            row = db.execute('SELECT source_id,bridge_port,enabled,token FROM xhs_sync_links WHERE owner=? AND account_id=?', (owner, account_id)).fetchone()
        require(row is not None, 'XHS_LOGIN_REQUIRED', '请先在本机绑定此账号的小红书登录会话')
        require(row[2], 'XHS_STOPPED', '账号连接已暂停；恢复后才能开展站内研究')
        require(not row[3], 'XHS_BUSY', '账号正在同步，请稍后再发起研究')
        return row[0], self.factory(port=row[1])

    def collect(self, owner, account_id, queries, check=lambda:None, style_filters=None, on_note=None, on_progress=None):
        require(isinstance(queries,list) and 1 <= len(queries) <= 2 and all(isinstance(q,str) and q.strip() for q in queries), 'INVALID_INPUT', '站内研究需要一至两个有效关键词')
        deadline=time.monotonic()+TASK_TIMEOUT_SECONDS
        expected, client = self.connection(owner, account_id)
        self.expected_source_id = expected
        counts=dict(raw_count=0,parsed_count=0,filtered_count=0,detail_success_count=0,detail_failed_count=0,invalid_count=0,duplicate_count=0,limit_count=0)
        notes, attempts, seen = [], [], set()
        def emit(phase,status,query=None,attempt=1,error=None,**extra):
            event=dict(phase=phase,status=status,attempt=attempt,counts=dict(counts),
                       raw_count=counts['raw_count'],parsed_count=counts['parsed_count'],filtered_count=counts['filtered_count'],**extra)
            if query is not None:event['query']=query
            if error is not None:
                event.update(error=error.code,error_origin=getattr(error,'error_origin',phase),mcp_http_status=getattr(error,'mcp_http_status',None))
            if on_progress:on_progress(event)
            return event
        def guard():
            check()
            require(time.monotonic()<deadline,'XHS_TASK_TIMEOUT','研究任务达到总时限；已取得候选保留')
            identity, _ = self.connection(owner, account_id)
            require(identity == expected, 'XHS_IDENTITY_CHANGED', '账号绑定已改变，停止研究')
        client.check=guard
        client.deadline=deadline
        def identity_check(phase):
            emit(phase,'started')
            try:
                guard()
                value=client.identity()
                require(isinstance(value,dict) and isinstance(value.get('id'),str),'XHS_PARSE','连接器身份响应格式异常')
                require(value['id']==expected,'XHS_IDENTITY_CHANGED','本机登录账号与绑定不符')
                guard()
            except DomainError as exc:
                emit(phase,'failed',error=exc);raise
            emit(phase,'done')
        identity_check('identity_initial')
        reads=0
        for query in queries:
            guard()
            result=None
            for attempt in (1,2):
                emit('search','started',query,attempt)
                try:
                    # Platform default results; no filter hover controls or topic branches.
                    result=client.search(query)
                    guard()
                    require(isinstance(result,dict) and isinstance(result.get('feeds'),list),'XHS_PARSE','站内搜索返回结构异常')
                except DomainError as exc:
                    event=emit('search','failed',query,attempt,error=exc)
                    attempts.append(event)
                    guard()
                    transient=exc.code in ('XHS_SEARCH_TIMEOUT','XHS_SEARCH_CONNECTION','XHS_SEARCH_HTTP_500','XHS_TIMEOUT','XHS_CONNECTION')
                    if attempt==1 and transient:
                        emit('search','retrying',query,attempt,error=exc)
                        until=time.monotonic()+RETRY_DELAY_SECONDS
                        while time.monotonic()<until:
                            guard();time.sleep(min(0.1,max(0,until-time.monotonic())))
                        continue
                    if not notes:raise
                    result=None;break
                break
            if result is None:break
            feeds=result['feeds']
            counts['raw_count']+=len(feeds)
            valid=[]
            for feed in feeds:
                if not isinstance(feed,dict) or not isinstance(feed.get('id'),str) or not feed['id'].strip() or not isinstance(feed.get('xsecToken'),str) or not feed['xsecToken'].strip():
                    counts['filtered_count']+=1;counts['invalid_count']+=1;continue
                valid.append(feed)
            counts['parsed_count']+=len(valid)
            if feeds and not valid:
                exc=DomainError('XHS_PARSE','搜索返回了记录但没有可解析笔记；未当作空结果')
                attempts.append(emit('search','failed',query,attempt,error=exc,outcome='invalid_records'))
                if not notes:raise exc
                break
            attempts.append(emit('search','done',query,attempt,results=len(feeds),sort_scope='returned_candidates_only',outcome='candidates' if valid else 'no_results'))
            preferred='collectedCount' if style_filters and style_filters.get('sort_by')=='favorites' else 'likedCount'
            def rank(feed):
                card=feed.get('noteCard') if isinstance(feed.get('noteCard'),dict) else {}
                info=card.get('interactInfo') if isinstance(card.get('interactInfo'),dict) else {}
                value=number(info.get(preferred))
                return (value is not None,value if value is not None else -1)
            for index,feed in enumerate(sorted(valid,key=rank,reverse=True)):
                if reads >= (6 if style_filters else 3) or len(notes)>=3:
                    counts['filtered_count']+=len(valid)-index
                    counts['limit_count']+=len(valid)-index
                    break
                identity, token = feed['id'],feed['xsecToken']
                if identity in seen:
                    counts['filtered_count']+=1;counts['duplicate_count']+=1
                    continue
                seen.add(identity);guard();reads+=1
                emit('detail','started',query,note_id=identity)
                try:
                    detail=client.request('/api/v1/feeds/detail',{'feed_id':identity,'xsec_token':token,'load_all_comments':False})
                    guard()
                    require(isinstance(detail,dict),'XHS_STRUCTURE','笔记详情响应结构异常')
                    detail=detail.get('data',detail)
                    require(isinstance(detail,dict) and isinstance(detail.get('note'),dict),'XHS_STRUCTURE','笔记详情结构异常')
                    note=detail['note']
                    require(note.get('noteId')==identity,'XHS_STRUCTURE','详情与搜索笔记不一致')
                    require(note.get('desc') is None or isinstance(note.get('desc'),str),'XHS_PARSE','笔记正文格式异常')
                    require(note.get('interactInfo') is None or isinstance(note.get('interactInfo'),dict),'XHS_PARSE','笔记互动格式异常')
                    require(note.get('user') is None or isinstance(note.get('user'),dict),'XHS_PARSE','笔记作者格式异常')
                    body=(note.get('desc') or '').strip()
                    info=note.get('interactInfo') or {}
                    metrics={key:number(info.get(raw)) for key,raw in METRIC_FIELDS}
                    metrics['views']=None
                    high_interaction=bool(style_filters and any(metrics[key] is not None and metrics[key]>=style_filters['min_'+key] for key in ('likes','favorites')))
                    published=None
                    if type(note.get('time')) is int:
                        try:published=datetime.fromtimestamp(note['time']/1000,timezone.utc).isoformat()
                        except (ValueError,OverflowError,OSError):pass
                    observed=datetime.now(timezone.utc).isoformat()
                    card=feed.get('noteCard') if isinstance(feed.get('noteCard'),dict) else {}
                    raw_kind=note.get('type') or card.get('type')
                    kind={'normal':'image','video':'video'}.get(raw_kind,'unknown') if isinstance(raw_kind,str) else 'unknown'
                    packet={'account_id':account_id,'title':str(note.get('title') or card.get('displayTitle') or '未取得标题')[:200],
                        'text':('【来源范围：视频笔记的文字描述；未读取音轨或转写视频】\n' if kind=='video' and body else '')+body[:99000],
                        'note_id':identity,'content_type':kind,'cover_url':cover_url(note,card),'body_kind':('video_description' if kind=='video' else 'full_text') if body else 'unread',
                        'source_url':original_url(note,feed,identity,token),'platform':'xiaohongshu',
                        'author':str((note.get('user') or {}).get('nickname') or '')[:200],
                        'published_at':published,'observed_at':observed,'content_kind':'text','evidence_role':'expression_reference',
                        'metrics':metrics,'metric_display':{key:str(info[raw])[:30] for key,raw in METRIC_FIELDS if isinstance(info.get(raw),(str,int)) and not isinstance(info.get(raw),bool) and str(info[raw]).strip()},'permission_confirmed':True}
                    if style_filters:packet['_provenance']={'visibility':'public','visibility_source':'platform_search_result','style_library_eligible':high_interaction,'high_engagement_supported':high_interaction,'style_selection':style_filters}
                    guard()
                    if on_note:on_note(dict(packet))
                    notes.append(packet);counts['detail_success_count']+=1
                    attempts.append(emit('detail','done',query,note_id=identity,outcome='readable' if body else 'unreadable'))
                except DomainError as exc:
                    counts['detail_failed_count']+=1
                    attempts.append(emit('detail','failed',query,error=exc,note_id=identity))
                    guard()
                    if exc.code in ('XHS_IDENTITY_CHANGED','XHS_STOPPED','RESEARCH_STOPPED','XHS_LOGIN_REQUIRED','XHS_RESTRICTED','XHS_TASK_TIMEOUT'):raise
                    continue
        identity_check('identity_final')
        guard()
        emit('complete','done',outcome='candidates' if notes else 'no_results' if counts['raw_count']==0 else 'no_readable_details')
        return notes, attempts

    def guard_save(self, db, owner, account_id):
        """Fence permission and the original identity in the document transaction."""
        row=db.execute('SELECT source_id,enabled FROM xhs_sync_links WHERE owner=? AND account_id=?',(owner,account_id)).fetchone()
        require(row and row[1],'XHS_STOPPED','账号连接已暂停；不保存迟到的研究结果')
        require(row[0]==self.expected_source_id,'XHS_IDENTITY_CHANGED','账号绑定已改变；不保存研究结果')


def original_url(note, feed, identity, token):
    for item in (note,feed):
        for key in ('shareUrl','share_url','url','noteUrl'):
            value=item.get(key)
            if not isinstance(value,str):continue
            try:parsed=urlsplit(value)
            except ValueError:continue
            if parsed.scheme=='https' and parsed.hostname in ('www.xiaohongshu.com','xiaohongshu.com','xhslink.com') and not parsed.username and not parsed.password:
                return value
    # Same canonical navigation URL as upstream xiaohongshu-mcp feed_detail.go;
    # the platform-returned access token is required to open a searched note.
    return 'https://www.xiaohongshu.com/explore/'+identity+'?'+urlencode({'xsec_token':token,'xsec_source':'pc_feed'})


def cover_url(note, card):
    values=[]
    if isinstance(card.get('cover'),dict):values.append(card['cover'])
    if isinstance(note.get('imageList'),list):values.extend(note['imageList'][:1])
    for item in values:
        if not isinstance(item,dict):continue
        for key in ('urlDefault','urlPre','url'):
            value=item.get(key)
            if not isinstance(value,str):continue
            try:parsed=urlsplit(value)
            except ValueError:continue
            if parsed.scheme in ('https','http') and parsed.hostname:return value
    return None


class LocalResearchClient(LocalXHS):
    def search(self, query, filters=None):
        # Only this fixed read-only endpoint is added; never a general proxy.
        req = urllib.request.Request(self.base+'/api/v1/feeds/search',
            # Omitting filters uses the platform's default comprehensive results
            # without interacting with its unstable filter/hover controls.
            data=json.dumps({'keyword':query},ensure_ascii=False).encode(),
            headers={'Authorization':'Bearer '+self.token_file.read_text(encoding='utf-8').strip(), 'Content-Type':'application/json'})
        try:
            body=self.read_response(req)
            require(len(body)<=8_000_000,'XHS_RESPONSE','搜索响应过大')
            result=json.loads(body)
            require(isinstance(result,dict) and result.get('success') is True and isinstance(result.get('data'),dict),'XHS_PARSE','本机搜索响应结构异常；不能据此判断登录失效')
            return result['data']
        except DomainError:raise
        except urllib.error.HTTPError as exc:
            raise http_failure(exc,'XHS_SEARCH') from None
        except TimeoutError:
            raise DomainError('XHS_SEARCH_TIMEOUT','本机搜索接口请求超时；本次不重试') from None
        except urllib.error.URLError as exc:
            code='XHS_SEARCH_TIMEOUT' if isinstance(exc.reason,TimeoutError) else 'XHS_SEARCH_CONNECTION'
            raise DomainError(code,'无法完成本机搜索接口连接；本次不重试') from None
        except (ConnectionError,OSError):
            raise DomainError('XHS_SEARCH_CONNECTION','本机搜索接口连接中断；本次不重试') from None
        except (ValueError,TypeError,AttributeError):
            raise DomainError('XHS_PARSE','本机搜索接口返回格式异常；本次不重试') from None
        except Exception:raise DomainError('XHS_TRANSPORT','站内搜索失败；本次不重试') from None

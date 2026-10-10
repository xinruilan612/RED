"""Explicit, bounded local-account public-note research; no write operations.

Public note access parameters are retained in original links; connector credentials are never exposed. Video descriptions are text evidence,
never claimed to be a watched video or a transcript.
"""
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlencode
from backend.contracts import DomainError, require
from backend.xhs_local import LocalXHS, number, http_failure


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

    def collect(self, owner, account_id, queries, check=lambda:None, style_filters=None, on_note=None):
        require(1 <= len(queries) <= 2, 'INVALID_INPUT', '站内研究最多两个关键词')
        expected, client = self.connection(owner, account_id)
        self.expected_source_id = expected
        def guard():
            check()
            identity, _ = self.connection(owner, account_id)
            require(identity == expected, 'XHS_IDENTITY_CHANGED', '账号绑定已改变，停止研究')
        client.check=guard
        guard()
        require(client.identity()['id'] == expected, 'XHS_IDENTITY_CHANGED', '本机登录账号与绑定不符')
        notes, attempts, seen = [], [], set()
        reads = 0
        for query in queries:
            guard()
            try:
                # No platform filter UI: upstream opens a hover panel for every
                # non-empty filter. Rank only this returned finite candidate set.
                result = client.search(query)
            except DomainError as exc:
                guard()
                if not notes:raise
                attempts.append({'query':query,'status':'failed','error':exc.code})
                break
            guard()
            feeds = result.get('feeds')
            require(isinstance(feeds, list), 'XHS_RESPONSE', '站内搜索返回格式异常')
            attempts.append({'query':query, 'status':'done', 'results':len(feeds), 'sort_scope':'returned_candidates_only'})
            preferred='collectedCount' if style_filters and style_filters.get('sort_by')=='favorites' else 'likedCount'
            def rank(feed):
                card=feed.get('noteCard',{}) if isinstance(feed,dict) else {}
                info=card.get('interactInfo',{}) if isinstance(card,dict) else {}
                value=number(info.get(preferred)) if isinstance(info,dict) else None
                return (value is not None,value if value is not None else -1)
            feeds=sorted(feeds,key=rank,reverse=True)
            for feed in feeds:
                if reads >= (6 if style_filters else 3) or len(notes)>=3:break
                if not isinstance(feed, dict):continue
                identity, token = feed.get('id'), feed.get('xsecToken')
                if not isinstance(identity,str) or not identity or identity in seen or not isinstance(token,str) or not token:continue
                seen.add(identity);guard();reads += 1
                try:
                    detail = client.request('/api/v1/feeds/detail', {'feed_id':identity, 'xsec_token':token, 'load_all_comments':False})
                    guard()
                    detail = detail.get('data', detail)
                    note = detail.get('note')
                    require(isinstance(note,dict) and note.get('noteId') == identity, 'XHS_STRUCTURE', '详情结构改变或与搜索笔记不一致')
                except DomainError as exc:
                    guard()
                    if exc.code in ('XHS_IDENTITY_CHANGED','XHS_STOPPED','RESEARCH_STOPPED','XHS_LOGIN_REQUIRED'):raise
                    attempts.append({'query':query,'note_id':identity,'status':'failed','error':exc.code})
                    continue
                body = str(note.get('desc') or '').strip()
                info = note.get('interactInfo') or {}
                metrics = {key:number(info.get(raw)) for key,raw in [('likes','likedCount'),('favorites','collectedCount'),('comments','commentCount'),('shares','sharedCount')]}
                metrics['views'] = None
                high_interaction = bool(style_filters and any(metrics[key] is not None and metrics[key]>=style_filters['min_'+key] for key in ('likes','favorites')))
                published = None
                if type(note.get('time')) is int:
                    try:published = datetime.fromtimestamp(note['time']/1000, timezone.utc).isoformat()
                    except (ValueError,OverflowError,OSError):pass
                observed = datetime.now(timezone.utc).isoformat()
                card=feed.get('noteCard') if isinstance(feed.get('noteCard'),dict) else {}
                kind={'normal':'image','video':'video'}.get(note.get('type') or card.get('type'),'unknown')
                notes.append({'account_id':account_id, 'title':str(note.get('title') or card.get('displayTitle') or '未取得标题')[:200],
                    'text':('【来源范围：视频笔记的文字描述；未读取音轨或转写视频】\n' if kind=='video' and body else '')+body[:99000],
                    'note_id':identity,'content_type':kind,'cover_url':cover_url(note,card),'body_kind':('video_description' if kind=='video' else 'full_text') if body else 'unread',
                    'source_url':original_url(note,feed,identity,token), 'platform':'xiaohongshu',
                    'author':str((note.get('user') or {}).get('nickname') or '')[:200],
                    'published_at':published, 'observed_at':observed, 'content_kind':'text',
                    'evidence_role':'expression_reference', 'metrics':metrics,
                    'metric_display':{key:str(info[raw])[:30] for key,raw in [('likes','likedCount'),('favorites','collectedCount'),('comments','commentCount'),('shares','sharedCount')] if isinstance(info.get(raw),(str,int)) and not isinstance(info.get(raw),bool) and str(info[raw]).strip()},
                    'permission_confirmed':True})
                if style_filters:
                    notes[-1]['_provenance']={'visibility':'public','visibility_source':'platform_search_result','style_library_eligible':high_interaction,'high_engagement_supported':high_interaction,'style_selection':style_filters}
                guard()
                if on_note:on_note(dict(notes[-1]))
        guard()
        require(client.identity()['id'] == expected, 'XHS_IDENTITY_CHANGED', '研究期间登录账号变化，结果不保存')
        guard()
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
            parsed=urlsplit(value)
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
            if isinstance(value,str) and urlsplit(value).scheme in ('https','http') and urlsplit(value).hostname:return value
    return None


class LocalResearchClient(LocalXHS):
    def search(self, query, filters=None):
        # Only this fixed read-only endpoint is added; never a general proxy.
        req = urllib.request.Request(self.base+'/api/v1/feeds/search',
            # Omitting filters uses the platform's default comprehensive results
            # without interacting with its unstable filter/hover controls.
            data=json.dumps({'keyword':query},ensure_ascii=False).encode(),
            headers={'Authorization':'Bearer '+self.token_file.read_text().strip(), 'Content-Type':'application/json'})
        try:
            body=self.read_response(req)
            require(len(body)<=8_000_000,'XHS_RESPONSE','搜索响应过大')
            result=json.loads(body)
            require(result.get('success') is True and isinstance(result.get('data'),dict),'XHS_RESPONSE','站内搜索不可用；请本人核对登录或访问限制')
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
            raise DomainError('XHS_RESPONSE','本机搜索接口返回格式异常；本次不重试') from None
        except Exception:raise DomainError('XHS_TRANSPORT','站内搜索失败；本次不重试') from None

"""Explicit, bounded local-account public-note research; no write operations.

Search tokens live only in this call. Video descriptions are text evidence,
never claimed to be a watched video or a transcript.
"""
import json
import urllib.request
from datetime import datetime, timezone
from backend.contracts import DomainError, require
from backend.xhs_local import LocalXHS, number


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

    def collect(self, owner, account_id, queries, check=lambda:None):
        require(1 <= len(queries) <= 2, 'INVALID_INPUT', '站内研究最多两个关键词')
        expected, client = self.connection(owner, account_id)
        def guard():
            check()
            identity, _ = self.connection(owner, account_id)
            require(identity == expected, 'XHS_IDENTITY_CHANGED', '账号绑定已改变，停止研究')
        guard()
        require(client.identity()['id'] == expected, 'XHS_IDENTITY_CHANGED', '本机登录账号与绑定不符')
        notes, attempts, seen = [], [], set()
        for query in queries:
            guard()
            result = client.search(query)
            feeds = result.get('feeds')
            require(isinstance(feeds, list), 'XHS_RESPONSE', '站内搜索返回格式异常')
            attempts.append({'query':query, 'status':'done', 'results':len(feeds)})
            for feed in feeds:
                if len(notes) >= 3:break
                if not isinstance(feed, dict):continue
                identity, token = feed.get('id'), feed.get('xsecToken')
                if not isinstance(identity,str) or not identity or identity in seen or not isinstance(token,str) or not token:continue
                seen.add(identity);guard()
                detail = client.request('/api/v1/feeds/detail', {'feed_id':identity, 'xsec_token':token, 'load_all_comments':False})
                detail = detail.get('data', detail)
                note = detail.get('note')
                require(isinstance(note,dict) and note.get('noteId') == identity, 'XHS_RESPONSE', '详情与搜索笔记不一致')
                body = str(note.get('desc') or '').strip()
                if not body:continue
                info = note.get('interactInfo') or {}
                metrics = {key:number(info.get(raw)) for key,raw in [('likes','likedCount'),('favorites','collectedCount'),('comments','commentCount'),('shares','sharedCount')]}
                metrics['views'] = None
                published = None
                if type(note.get('time')) is int:
                    try:published = datetime.fromtimestamp(note['time']/1000, timezone.utc).isoformat()
                    except (ValueError,OverflowError,OSError):pass
                observed = datetime.now(timezone.utc).isoformat()
                notes.append({'account_id':account_id, 'title':str(note.get('title') or '小红书视频描述')[:200],
                    'text':'【来源范围：视频笔记的文字描述；未读取音轨或转写视频】\n'+body[:99000],
                    'source_url':'https://www.xiaohongshu.com/explore/'+identity, 'platform':'xiaohongshu',
                    'author':str((note.get('user') or {}).get('nickname') or '')[:200],
                    'published_at':published, 'observed_at':observed, 'content_kind':'text',
                    'evidence_role':'expression_reference', 'metrics':metrics, 'permission_confirmed':True})
        guard()
        require(client.identity()['id'] == expected, 'XHS_IDENTITY_CHANGED', '研究期间登录账号变化，结果不保存')
        return notes, attempts


class LocalResearchClient(LocalXHS):
    def search(self, query):
        # Only this fixed read-only endpoint is added; never a general proxy.
        req = urllib.request.Request(self.base+'/api/v1/feeds/search',
            data=json.dumps({'keyword':query,'filters':{'sort_by':'最多点赞','note_type':'视频','publish_time':'半年内'}},ensure_ascii=False).encode(),
            headers={'Authorization':'Bearer '+self.token_file.read_text().strip(), 'Content-Type':'application/json'})
        try:
            with self.opener.open(req, timeout=85) as response:body=response.read(8_000_001)
            require(len(body)<=8_000_000,'XHS_RESPONSE','搜索响应过大')
            result=json.loads(body)
            require(result.get('success') is True and isinstance(result.get('data'),dict),'XHS_RESPONSE','站内搜索不可用；请本人核对登录或访问限制')
            return result['data']
        except DomainError:raise
        except Exception:raise DomainError('XHS_TRANSPORT','站内搜索失败；本次不重试') from None

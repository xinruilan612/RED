"""Persistent, bounded polling of one explicitly bound local creator session.

Stored separately from manual metrics: browser observations are not official API
verification, and partial comment coverage is never interpreted as deletion.
"""
import hashlib
import json
import time
import math
import re
from datetime import date, datetime, timezone
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4
from backend.accounts import find_account
from backend.contracts import DomainError, require
from backend.operations import Operations
from backend.xhs_local import LocalXHS
from backend.creator_metrics import PUBLIC_VISIBILITY_SOURCE


def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


CREATOR_COUNTS=('exposure','views','likes','favorites','comments','shares')
CREATOR_RATES=('cover_ctr','video_completion_rate','avg_watch_seconds','avg_view_duration','total_watch_seconds')


def creator_snapshot(raw,source_id):
    """Validate the optional channel independently; never discard comment data."""
    empty={'status':'unavailable','observed_at':None,'source_updated_at':None,'source_method':'creator_browser_dom',
           'source_id':source_id,'official_api':False,'account':None,'notes':[],'error':None}
    if raw is None:return empty
    try:
        require(isinstance(raw,dict),'XHS_CREATOR_RESPONSE','创作者数据格式无效')
        status=raw.get('status')
        require(status in ('synced','partial','failed','unavailable'),'XHS_CREATOR_RESPONSE','创作者状态无效')
        observed=raw.get('observed_at')
        if observed is not None:
            require(isinstance(observed,str) and len(observed)<=50,'XHS_CREATOR_RESPONSE','观测时间无效')
            parsed=datetime.fromisoformat(observed.replace('Z','+00:00'))
            require(parsed.tzinfo is not None and parsed<=datetime.now(timezone.utc),'XHS_CREATOR_RESPONSE','观测时间无效')
            observed=parsed.astimezone(timezone.utc).isoformat()
        error=raw.get('error')
        error=error if isinstance(error,str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',error) else None
        result={**empty,'status':status,'observed_at':observed,'error':error}
        if status in ('failed','unavailable'):return result
        require(raw.get('source_id')==source_id,'XHS_IDENTITY_CHANGED','创作者身份不匹配')
        require(observed is not None,'XHS_CREATOR_RESPONSE','缺少观测时间')
        creator_id=raw.get('creator_account_id')
        require(creator_id is None or isinstance(creator_id,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}',creator_id),'XHS_CREATOR_RESPONSE','创作者账号标识无效')
        result['creator_account_id']=creator_id
        def display(value,maximum=100):
            return value if isinstance(value,str) and len(value)<=maximum else None
        def displays(values):
            if not isinstance(values,dict):return {}
            return {key:display(values[key],120) for key in CREATOR_COUNTS+CREATOR_RATES if key in values}
        def metrics(values):
            require(isinstance(values,dict),'XHS_CREATOR_RESPONSE','指标结构无效')
            clean={k:(values.get(k) if type(values.get(k)) is int and (-10**12 if k=='followers_gained' else 0)<=values[k]<=10**12 else None) for k in CREATOR_COUNTS}
            for key in CREATOR_RATES:
                value=values.get(key);maximum=100 if key in ('cover_ctr','video_completion_rate') else 10**12
                clean[key]=value if type(value) in (int,float) and math.isfinite(value) and 0<=value<=maximum else None
            return clean
        account=raw.get('account')
        if account is not None:
            require(isinstance(account,dict),'XHS_CREATOR_RESPONSE','账号周期结构无效')
            period={key:account.get(key) for key in ('period_start','period_end')}
            for value in period.values():
                if value is not None:
                    require(isinstance(value,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',value),'XHS_CREATOR_RESPONSE','周期日期无效')
                    date.fromisoformat(value)
            require(not all(period.values()) or period['period_start']<=period['period_end'],'XHS_CREATOR_RESPONSE','周期范围无效')
            days=account.get('period_days')
            require(days is None or type(days) is int and 1<=days<=3660,'XHS_CREATOR_RESPONSE','周期天数无效')
            result['account']={**period,'period_days':days,'period_display':display(account.get('period_display')),
                               'metrics':metrics(account.get('metrics',{})),'metric_displays':displays(account.get('metric_displays'))}
        notes=raw.get('notes',[])
        require(isinstance(notes,list) and len(notes)<=100,'XHS_CREATOR_RESPONSE','笔记数据超限')
        seen=set()
        for note in notes:
            if not isinstance(note,dict) or note.get('visibility')!='public' or note.get('visibility_source')!=PUBLIC_VISIBILITY_SOURCE:
                continue
            require(isinstance(note,dict) and isinstance(note.get('id'),str) and re.fullmatch(r'[A-Za-z0-9_-]{1,200}',note['id']),'XHS_CREATOR_RESPONSE','笔记标识无效')
            if note['id'] in seen:continue
            seen.add(note['id'])
            url=note.get('source_url') or 'https://www.xiaohongshu.com/explore/'+note['id']
            require(isinstance(url,str) and len(url)<=2048,'XHS_CREATOR_RESPONSE','来源链接无效')
            parsed=urlsplit(url)
            require(parsed.scheme=='https' and parsed.netloc in ('www.xiaohongshu.com','creator.xiaohongshu.com'),'XHS_CREATOR_RESPONSE','来源链接无效')
            result['notes'].append({'id':note['id'],'title':display(note.get('title'),500),
                'visibility':'public','visibility_source':PUBLIC_VISIBILITY_SOURCE,
                'published_display':display(note.get('published_display')),
                'metrics':metrics(note.get('metrics',{})),'metric_displays':displays(note.get('metric_displays')),
                'source_url':urlunsplit((parsed.scheme,parsed.netloc,parsed.path,'',''))})
        require(result['account'] is not None or bool(result['notes']),'XHS_CREATOR_RESPONSE','创作者结果为空')
        return result
    except (DomainError,ValueError,TypeError) as exc:
        return {**empty,'status':'failed','error':exc.code if isinstance(exc,DomainError) else 'XHS_CREATOR_RESPONSE'}


class XHSSync:
    def __init__(self,store,client_factory=None):
        self.store=store;self.factory=client_factory or (lambda port:LocalXHS(port=port))

    @staticmethod
    def public_note_ids(db,owner,account_id):
        """Only the latest verified creator snapshot can grant public visibility.

        Old observations without an explicit DOM visibility marker remain stored
        for audit but never authorize API responses, comments, or case imports.
        """
        row=db.execute("SELECT e.payload,l.source_id FROM xhs_sync_entities e JOIN xhs_sync_links l ON l.owner=e.owner AND l.account_id=e.account_id WHERE e.owner=? AND e.account_id=? AND e.kind='creator_account' AND e.id='snapshot'",(owner,account_id)).fetchone()
        if not row:return set()
        snapshot=json.loads(row[0])
        if snapshot.get('source_id')!=row[1] or snapshot.get('status') not in ('synced','partial'):return set()
        return {n['id'] for n in snapshot.get('notes',[]) if isinstance(n,dict) and isinstance(n.get('id'),str)
                and n.get('visibility')=='public' and n.get('visibility_source')==PUBLIC_VISIBILITY_SOURCE}

    @staticmethod
    def require_public_note(db,owner,account_id,note_id):
        require(note_id in XHSSync.public_note_ids(db,owner,account_id),'RESOURCE_NOT_FOUND','笔记尚未核实为公开内容，不能读取或导入')

    @staticmethod
    def _public_creator(snapshot,visible):
        if not isinstance(snapshot,dict):return None
        # Home aggregates include private posts and cannot be attributed to a
        # public post. Historical aggregates remain only in persisted audit data.
        notes=[]
        for note in snapshot.get('notes',[]):
            if not isinstance(note,dict) or note.get('id') not in visible or note.get('visibility')!='public' or note.get('visibility_source')!=PUBLIC_VISIBILITY_SOURCE:continue
            notes.append({**note,'metrics':{k:v for k,v in note.get('metrics',{}).items() if k in CREATOR_COUNTS+CREATOR_RATES},
                          'metric_displays':{k:v for k,v in note.get('metric_displays',{}).items() if k in CREATOR_COUNTS+CREATOR_RATES}})
        return {**snapshot,'account':None,'notes':notes}

    def bind(self,owner,account_id,port=18061,interval_s=900):
        account=find_account(Operations(self.store).read(owner),account_id)
        require(account['platform']=='xiaohongshu','INVALID_INPUT','只能绑定小红书账号档案')
        require(type(interval_s) is int and 300<=interval_s<=86400,'INVALID_INPUT','同步间隔须为5分钟至24小时')
        identity=self.factory(port).identity()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            conflict=db.execute('SELECT owner,account_id FROM xhs_sync_links WHERE source_id=? OR bridge_port=?',(identity['id'],port)).fetchall()
            require(all(r[0]==owner and r[1]==account_id for r in conflict),'FORBIDDEN','此本机登录会话已绑定其他网站账号；禁止串用')
            existing=db.execute('SELECT source_id,token FROM xhs_sync_links WHERE owner=? AND account_id=?',(owner,account_id)).fetchone()
            require(not existing or existing[0]==identity['id'],'XHS_IDENTITY_CHANGED','账号身份改变，不能覆盖原绑定与历史')
            require(not existing or not existing[1],'INVALID_TRANSITION','正在同步，请先暂停后修改')
            db.execute('INSERT INTO xhs_sync_links(owner,account_id,source_id,bridge_port,interval_s,enabled,status,next_at) VALUES(?,?,?,?,?,1,?,?) ON CONFLICT(owner,account_id) DO UPDATE SET interval_s=excluded.interval_s,enabled=1,status=excluded.status,next_at=excluded.next_at,error=NULL,failures=0',
                       (owner,account_id,identity['id'],port,interval_s,'ready',time.time()))
        return self.public(owner,account_id)

    def public(self,owner,account_id):
        find_account(Operations(self.store).read(owner),account_id)
        with self.store.connect() as db:
            row=db.execute('SELECT source_id,interval_s,enabled,status,next_at,last_at,error FROM xhs_sync_links WHERE owner=? AND account_id=?',(owner,account_id)).fetchone()
            if not row:return {'bound':False,'enabled':False,'status':'not_connected'}
            visible=self.public_note_ids(db,owner,account_id)
            entities=db.execute("SELECT kind,id,payload FROM xhs_sync_entities WHERE owner=? AND account_id=? AND kind IN ('note','comment')",(owner,account_id)).fetchall()
            counts={'note':sum(r[0]=='note' and r[1] in visible for r in entities),
                    'comment':sum(r[0]=='comment' and json.loads(r[2]).get('note_id') in visible for r in entities)}
            latest=db.execute('SELECT payload FROM xhs_sync_rounds WHERE owner=? AND account_id=? ORDER BY observed_at DESC LIMIT 1',(owner,account_id)).fetchone()
            latest=json.loads(latest[0]) if latest else None
            creator=db.execute("SELECT payload FROM xhs_sync_entities WHERE owner=? AND account_id=? AND kind='creator_account' AND id='snapshot'",(owner,account_id)).fetchone()
            if latest:
                all_visible=all(n.get('id') in visible for n in latest.get('notes',[]))
                latest['notes']=[{**n,'visibility':'public','visibility_source':PUBLIC_VISIBILITY_SOURCE} for n in latest.get('notes',[]) if n.get('id') in visible]
                latest['creator_metrics']=self._public_creator(latest.get('creator_metrics'),visible)
                summary=latest.get('summary',{})
                latest['summary']={**summary,'notes_read':len(latest['notes']),
                    'comments_read':sum(len(n.get('comments',[])) for n in latest['notes']),
                    'failures':[f for f in summary.get('failures',[]) if f.get('note_id') in visible],
                    **{key:summary.get(key) if all_visible else None for key in ('new_notes','changed_notes','new_comments','changed_comments')}}
            return {'bound':True,'source_id':row[0],'interval_s':row[1],'enabled':bool(row[2]),'status':row[3],
                    'next_at':row[4] if row[2] else None,'last_at':row[5],'error':row[6],'counts':counts,
                    'latest_round':latest,'official_api':False,'realtime_push':False,
                    'creator_metrics':latest.get('creator_metrics') if latest else None,
                    'creator_last_success':self._public_creator(json.loads(creator[0]),visible) if creator else None,
                    'limitation':'仅返回经创作者笔记管理页面核实的公开笔记；私密与可见性未核实记录不展示。逐篇指标缺失保留未知。'}

    def control(self,owner,account_id,action):
        require(action in ('pause','resume','refresh'),'INVALID_INPUT','同步操作无效')
        find_account(Operations(self.store).read(owner),account_id)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT enabled,token,next_at,last_at FROM xhs_sync_links WHERE owner=? AND account_id=?',(owner,account_id)).fetchone()
            require(row is not None,'RESOURCE_NOT_FOUND','此账号尚未绑定本机同步器')
            if action=='pause':
                db.execute("UPDATE xhs_sync_links SET enabled=0,status='paused',token=NULL,lease_until=NULL WHERE owner=? AND account_id=?",(owner,account_id))
            else:
                require(not row[1],'INVALID_TRANSITION','本轮仍在读取，不重复提交')
                if action=='refresh':require(row[3] is None or time.time()-row[3]>=60,'RATE_LIMITED','两次手动核对至少间隔60秒')
                db.execute("UPDATE xhs_sync_links SET enabled=1,status='ready',next_at=?,error=NULL,failures=0 WHERE owner=? AND account_id=?",(time.time(),owner,account_id))
        return self.public(owner,account_id)

    def records(self,owner,account_id):
        find_account(Operations(self.store).read(owner),account_id)
        with self.store.connect() as db:
            visible=self.public_note_ids(db,owner,account_id)
            rows=db.execute("SELECT payload FROM xhs_sync_entities WHERE owner=? AND account_id=? AND kind='note' ORDER BY last_seen DESC LIMIT 30",(owner,account_id)).fetchall()
            creator=db.execute("SELECT id,payload FROM xhs_sync_entities WHERE owner=? AND account_id=? AND kind='creator_note'",(owner,account_id)).fetchall()
        creator={r[0]:json.loads(r[1]) for r in creator if json.loads(r[1]).get('visibility')=='public'
                 and json.loads(r[1]).get('visibility_source')==PUBLIC_VISIBILITY_SOURCE}
        creator={identity:self._public_creator({'notes':[value]},visible)['notes'][0]
                 for identity,value in creator.items() if identity in visible}
        return [{**json.loads(r[0]),'creator_metrics':creator.get(json.loads(r[0])['id']),
                 'visibility':'public','visibility_source':PUBLIC_VISIBILITY_SOURCE}
                for r in rows if json.loads(r[0])['id'] in visible]

    def reconnect(self,owner,account_id):
        find_account(Operations(self.store).read(owner),account_id)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT bridge_port FROM xhs_sync_links WHERE owner=? AND account_id=?',(owner,account_id)).fetchone()
            require(row is not None,'RESOURCE_NOT_FOUND','仅已有绑定账号可以重新登录')
            db.execute("UPDATE xhs_sync_links SET enabled=0,status='paused',token=NULL,lease_until=NULL WHERE owner=? AND account_id=?",(owner,account_id))
        return self.factory(row[0]).reconnect()

    def comments(self,owner,account_id,note_id,offset=0):
        find_account(Operations(self.store).read(owner),account_id)
        require(isinstance(note_id,str) and 0<len(note_id)<=200,'INVALID_INPUT','笔记标识无效')
        require(type(offset) is int and 0<=offset<=100000,'INVALID_INPUT','评论分页位置无效')
        with self.store.connect() as db:
            self.require_public_note(db,owner,account_id,note_id)
            note=db.execute("SELECT id FROM xhs_sync_entities WHERE owner=? AND account_id=? AND kind='note' AND id=?",(owner,account_id,note_id)).fetchone()
            require(note is not None,'RESOURCE_NOT_FOUND','未找到此账号的已保存笔记')
            # IDs are composite; exact prefix comparison avoids LIKE wildcard input.
            prefix=note_id+':'
            rows=db.execute("SELECT payload,first_seen,last_seen FROM xhs_sync_entities WHERE owner=? AND account_id=? AND kind='comment' AND substr(id,1,?)=? ORDER BY first_seen DESC,id LIMIT 51 OFFSET ?",(owner,account_id,len(prefix),prefix,offset)).fetchall()
        return {'items':[{**json.loads(r[0]),'first_seen':r[1],'last_seen':r[2]} for r in rows[:50]],
                'next_offset':offset+50 if len(rows)>50 else None,'coverage':'historically_observed_not_complete'}

    def _claim(self):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');now=time.time()
            db.execute("UPDATE xhs_sync_links SET status='retrying',token=NULL,lease_until=NULL,next_at=? WHERE enabled=1 AND token IS NOT NULL AND lease_until<=?",(now+300,now))
            row=db.execute('SELECT owner,account_id,source_id,bridge_port,interval_s FROM xhs_sync_links WHERE enabled=1 AND token IS NULL AND next_at<=? ORDER BY next_at LIMIT 1',(now,)).fetchone()
            if not row:return None
            token=str(uuid4())
            db.execute("UPDATE xhs_sync_links SET token=?,lease_until=?,status='syncing' WHERE owner=? AND account_id=?",(token,now+900,row[0],row[1]))
            return dict(zip(('owner','account','source','port','interval','token'),(*row,token)))

    @staticmethod
    def _guard(db,job):
        row=db.execute('SELECT enabled,token,lease_until,source_id FROM xhs_sync_links WHERE owner=? AND account_id=?',(job['owner'],job['account'])).fetchone()
        require(row and row[0] and row[1]==job['token'] and row[2]>time.time(),'XHS_STOPPED','同步已暂停或租约已失效')
        require(row[3]==job['source'],'XHS_IDENTITY_CHANGED','账号绑定已变化，不保存迟到数据')

    def _heartbeat(self,job):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');self._guard(db,job)
            db.execute('UPDATE xhs_sync_links SET lease_until=? WHERE owner=? AND account_id=?',(time.time()+900,job['owner'],job['account']))

    def once(self):
        job=self._claim()
        if not job:return False
        try:
            result=self.factory(job['port']).collect(job['source'],limit=5,check=lambda:self._heartbeat(job))
            self._save(job,result)
        except Exception as exc:
            code=exc.code if isinstance(exc,DomainError) else 'XHS_TRANSPORT'
            if code=='XHS_STOPPED':return True
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                try:self._guard(db,job)
                except DomainError:return True
                failures=db.execute('SELECT failures FROM xhs_sync_links WHERE owner=? AND account_id=?',(job['owner'],job['account'])).fetchone()[0]+1
                stop=code in ('XHS_LOGIN_REQUIRED','XHS_IDENTITY_UNVERIFIED','XHS_IDENTITY_CHANGED','XHS_RESPONSE') or failures>=3
                delay=min(86400,job['interval']*2**min(failures,6))
                db.execute('UPDATE xhs_sync_links SET enabled=?,status=?,error=?,failures=?,next_at=?,token=NULL,lease_until=NULL WHERE owner=? AND account_id=?',
                           (0 if stop else 1,'needs_attention' if stop else 'retrying',code,failures,time.time()+delay,job['owner'],job['account']))
        return True

    def _save(self,job,result):
        require(result['identity']['id']==job['source'],'XHS_IDENTITY_CHANGED','返回账号与绑定不符')
        require(bool(result['notes']) or not result['failures'],'XHS_RESPONSE','本轮所有笔记读取失败，暂停等待检查')
        now=time.time();stats={'new_notes':0,'changed_notes':0,'new_comments':0,'changed_comments':0}
        creator=creator_snapshot(result.get('creator_metrics'),job['source'])
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');self._guard(db,job)
            def save(kind,identity,value):
                payload=encoded(value);digest=hashlib.sha256(payload.encode()).hexdigest()
                old=db.execute('SELECT hash FROM xhs_sync_entities WHERE owner=? AND account_id=? AND kind=? AND id=?',(job['owner'],job['account'],kind,identity)).fetchone()
                if kind in ('note','comment') and (not old or old[0]!=digest):stats[('new_' if not old else 'changed_')+kind+'s']+=1
                db.execute('INSERT INTO xhs_sync_entities VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(owner,account_id,kind,id) DO UPDATE SET payload=excluded.payload,hash=excluded.hash,last_seen=excluded.last_seen',
                           (job['owner'],job['account'],kind,identity,payload,digest,now,now))
            for note in result['notes']:
                save('note',note['id'],{k:v for k,v in note.items() if k!='comments'})
                for comment in note['comments']:save('comment',note['id']+':'+comment['id'],{**comment,'note_id':note['id']})
            if creator['status'] in ('synced','partial'):
                save('creator_account','snapshot',creator)
                for note in creator['notes']:
                    save('creator_note',note['id'],{**note,'observed_at':creator['observed_at'],'source_updated_at':None,
                        'source_method':'creator_browser_dom','source_id':job['source'],'official_api':False})
            summary={**stats,'notes_read':len(result['notes']),'comments_read':sum(len(n['comments']) for n in result['notes']),
                     'failures':result['failures'],'observed_at':result['observed_at'],'source_updated_at':None,
                     'source_method':'local_browser_mcp','coverage':result['coverage'],'official_api':False}
            db.execute('INSERT INTO xhs_sync_rounds VALUES(?,?,?,?,?)',(str(uuid4()),job['owner'],job['account'],now,encoded({'summary':summary,'notes':result['notes'],'creator_metrics':creator})))
            partial=bool(result['failures']) or creator['status'] in ('partial','failed')
            db.execute('UPDATE xhs_sync_links SET status=?,last_at=?,next_at=?,error=NULL,failures=0,token=NULL,lease_until=NULL WHERE owner=? AND account_id=?',
                       ('partial' if partial else 'synced',now,now+job['interval'],job['owner'],job['account']))

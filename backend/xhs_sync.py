"""Persistent, bounded polling of one explicitly bound local creator session.

Stored separately from manual metrics: browser observations are not official API
verification, and partial comment coverage is never interpreted as deletion.
"""
import hashlib
import json
import time
from uuid import uuid4
from backend.accounts import find_account
from backend.contracts import DomainError, require
from backend.operations import Operations
from backend.xhs_local import LocalXHS


def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


class XHSSync:
    def __init__(self,store,client_factory=None):
        self.store=store;self.factory=client_factory or (lambda port:LocalXHS(port=port))

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
            counts={kind:db.execute('SELECT COUNT(*) FROM xhs_sync_entities WHERE owner=? AND account_id=? AND kind=?',(owner,account_id,kind)).fetchone()[0] for kind in ('note','comment')}
            latest=db.execute('SELECT payload FROM xhs_sync_rounds WHERE owner=? AND account_id=? ORDER BY observed_at DESC LIMIT 1',(owner,account_id)).fetchone()
            return {'bound':True,'source_id':row[0],'interval_s':row[1],'enabled':bool(row[2]),'status':row[3],
                    'next_at':row[4] if row[2] else None,'last_at':row[5],'error':row[6],'counts':counts,
                    'latest_round':json.loads(latest[0]) if latest else None,'official_api':False,'realtime_push':False,
                    'limitation':'本机浏览器定时读取；前5篇笔记、每篇最多100条已加载评论，不保证全量。曝光/阅读暂无来源。'}

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
            rows=db.execute("SELECT payload FROM xhs_sync_entities WHERE owner=? AND account_id=? AND kind='note' ORDER BY last_seen DESC LIMIT 30",(owner,account_id)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def comments(self,owner,account_id,note_id,offset=0):
        find_account(Operations(self.store).read(owner),account_id)
        require(isinstance(note_id,str) and 0<len(note_id)<=200,'INVALID_INPUT','笔记标识无效')
        require(type(offset) is int and 0<=offset<=100000,'INVALID_INPUT','评论分页位置无效')
        with self.store.connect() as db:
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
        row=db.execute('SELECT enabled,token,lease_until FROM xhs_sync_links WHERE owner=? AND account_id=?',(job['owner'],job['account'])).fetchone()
        require(row and row[0] and row[1]==job['token'] and row[2]>time.time(),'XHS_STOPPED','同步已暂停或租约已失效')

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
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');self._guard(db,job)
            def save(kind,identity,value):
                payload=encoded(value);digest=hashlib.sha256(payload.encode()).hexdigest()
                old=db.execute('SELECT hash FROM xhs_sync_entities WHERE owner=? AND account_id=? AND kind=? AND id=?',(job['owner'],job['account'],kind,identity)).fetchone()
                if not old or old[0]!=digest:stats[('new_' if not old else 'changed_')+kind+'s']+=1
                db.execute('INSERT INTO xhs_sync_entities VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(owner,account_id,kind,id) DO UPDATE SET payload=excluded.payload,hash=excluded.hash,last_seen=excluded.last_seen',
                           (job['owner'],job['account'],kind,identity,payload,digest,now,now))
            for note in result['notes']:
                save('note',note['id'],{k:v for k,v in note.items() if k!='comments'})
                for comment in note['comments']:save('comment',note['id']+':'+comment['id'],{**comment,'note_id':note['id']})
            summary={**stats,'notes_read':len(result['notes']),'comments_read':sum(len(n['comments']) for n in result['notes']),
                     'failures':result['failures'],'observed_at':result['observed_at'],'source_updated_at':None,
                     'source_method':'local_browser_mcp','coverage':result['coverage'],'official_api':False}
            db.execute('INSERT INTO xhs_sync_rounds VALUES(?,?,?,?,?)',(str(uuid4()),job['owner'],job['account'],now,encoded({'summary':summary,'notes':result['notes']})))
            partial=bool(result['failures'])
            db.execute('UPDATE xhs_sync_links SET status=?,last_at=?,next_at=?,error=NULL,failures=0,token=NULL,lease_until=NULL WHERE owner=? AND account_id=?',
                       ('partial' if partial else 'synced',now,now+job['interval'],job['owner'],job['account']))

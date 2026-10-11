"""Bounded durable research; interrupted paid searches are never replayed."""
import json
import hashlib
import time
from uuid import uuid4

from backend.accounts import find_account
from backend.contracts import DomainError, require
from backend.operations import Operations
from backend.research_access import require_readable_source
from backend.research_cases import ResearchCases, safe
from backend.search_providers import SearchSettings, target_domains
from backend.sources import public_url, read_article
from backend.workflow import digest

LEASE_SECONDS = 120
TASK_SECONDS = 180
QUEUE_SECONDS = 300
TERMINAL = ('done', 'partial', 'failed', 'interrupted', 'cancelled')


class ResearchJobs:
    def __init__(self, store, searcher=None, reader=None, cases=None):
        self.store = store
        self.searcher = searcher or SearchSettings(store)
        self.reader = reader or read_article
        self.cases = cases or ResearchCases(store)

    def create(self, owner, data):
        fields = {'account_id', 'queries', 'provider', 'targets', 'evidence_role', 'permission_confirmed', 'key'}
        require(isinstance(data, dict) and fields <= set(data) <= fields | {'style_filters', 'confirmation_required'}, 'INVALID_INPUT', '研究任务字段无效')
        require(isinstance(data['key'], str) and 1 <= len(data['key']) <= 160,
                'INVALID_INPUT', '请提供任务幂等编号')
        queries = data['queries']
        require(isinstance(queries, list) and 1 <= len(queries) <= 2 and
                all(isinstance(q, str) and 2 <= len(q.strip()) <= 120 for q in queries),
                'INVALID_INPUT', '研究任务限 1 至 2 个搜索词，每个 2 至 120 字符')
        require(data['provider'] in ('bing', 'wikipedia', 'baidu', 'xhs_local'), 'INVALID_INPUT', '搜索服务无效')
        domains = target_domains(data['targets'])
        require(data['provider'] != 'wikipedia' or not domains, 'INVALID_INPUT', '百科仅支持全网范围')
        require(data['evidence_role'] in ('expression_reference', 'product_fact') and
                data['permission_confirmed'] is True, 'INVALID_INPUT', '请选择资料用途并确认保存权限')
        find_account(Operations(self.store).read(owner), data['account_id'])
        if data['provider'] == 'xhs_local':
            require(data['targets'] == ['xiaohongshu'] and data['evidence_role'] == 'expression_reference', 'INVALID_INPUT', '站内视频研究只支持小红书表达参考')
            from backend.xhs_research import XHSResearch
            XHSResearch(self.store).connection(owner, data['account_id'])
        if 'style_filters' in data:
            filters=data['style_filters']
            require(data['provider']=='xhs_local' and isinstance(filters,dict) and set(filters)=={'min_likes','min_favorites','sort_by'} and
                    all(type(filters[k]) is int and 1<=filters[k]<=10**9 for k in ('min_likes','min_favorites')) and
                    filters['sort_by'] in ('likes','favorites'), 'INVALID_INPUT','赞藏筛选字段无效')
        require(type(data.get('confirmation_required', False)) is bool, 'INVALID_INPUT', '确认设置无效')
        raw_queries = list(queries)
        data = dict(data)
        data['queries'] = list(dict.fromkeys(' '.join(q.split()) for q in queries))
        data['targets'] = sorted(set(data['targets']))
        data['confirmation_required'] = True if data['provider']=='xhs_local' else data.get('confirmation_required',False)
        scope = self._scope(data)
        fingerprint = digest(scope)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._expire(db)
            prior = db.execute('SELECT id,fingerprint FROM research_jobs WHERE owner=? AND key=?', (owner, data['key'])).fetchone()
            if prior:
                previous=self._get(db,owner,prior[0])
                require(self._scope(previous)==scope, 'IDEMPOTENCY_CONFLICT', '相同任务编号不能提交不同研究范围')
                return self._reuse(self._public_view(db,owner,previous),'idempotent_task')
            for active in db.execute("SELECT id,payload FROM research_jobs WHERE owner=? AND account_id=? AND status IN ('queued','running')", (owner,data['account_id'])):
                current = json.loads(active[1])
                if self._scope(current)==scope:
                    return self._reuse(self._public_view(db,owner,self._get(db,owner,active[0])),'active_task')
            count = db.execute("SELECT COUNT(*) FROM research_jobs WHERE owner=? AND status IN ('queued','running')", (owner,)).fetchone()[0]
            require(count < 3, 'QUOTA_EXCEEDED', '最多同时保留 3 个待执行研究任务')
            identity, now = str(uuid4()), time.time()
            payload = dict(scope)
            payload.update(raw_queries=raw_queries, attempts=[], items=[],
                           trace=[],phase='queued',counts={},outcome=None,error_origin=None,
                           queue_deadline_at=now+QUEUE_SECONDS,
                           document_ids=[], candidates=[], report=None, error=None,
                           limits={'max_queries': 2, 'max_pages': 6, 'max_documents': 3})
            db.execute('INSERT INTO research_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (identity, owner, data['account_id'], data['key'], fingerprint, 'queued',
                        json.dumps(payload, ensure_ascii=False), None, None, now, now))
            return self._reuse(self._get(db, owner, identity),'new_task')

    @staticmethod
    def _scope(data):
        return {'account_id':data['account_id'], 'queries':list(dict.fromkeys(' '.join(q.split()) for q in data['queries'])),
                'provider':data['provider'],'targets':sorted(set(data['targets'])),
                'evidence_role':data['evidence_role'],'permission_confirmed':data['permission_confirmed'],
                'confirmation_required':True if data['provider']=='xhs_local' else data.get('confirmation_required',False),
                'style_filters':data.get('style_filters')}

    @staticmethod
    def _reuse(job, kind):
        return {**job,'reuse':{'kind':kind,'cache_hit':False,'task_id':job['id']}}

    @staticmethod
    def _get(db, owner, identity):
        row = db.execute('SELECT id,account_id,status,payload,created_at,updated_at FROM research_jobs WHERE id=? AND owner=?', (identity, owner)).fetchone()
        require(row is not None, 'RESOURCE_NOT_FOUND', '研究任务不可访问')
        payload = json.loads(row[3])
        return dict(id=row[0], status=row[2], **payload, created_at=row[4], updated_at=row[5],
                    documents=[{'id': item['document_id'], 'title': item['title']} for item in payload['items'] if item['status']=='saved'],
                    searches=payload['attempts'], reads=payload['items'])

    @staticmethod
    def _expire(db):
        now=time.time()
        for identity,status,encoded,created,lease in db.execute("SELECT id,status,payload,created_at,lease_until FROM research_jobs WHERE status IN ('queued','running')").fetchall():
            payload=json.loads(encoded)
            deadline=payload.get('queue_deadline_at',created+QUEUE_SECONDS) if status=='queued' else payload.get('deadline_at',created+TASK_SECONDS)
            if deadline>now and (status!='running' or lease is not None and lease>now):continue
            absolute=deadline<=now
            code='RESEARCH_QUEUE_TIMEOUT' if status=='queued' else 'RESEARCH_TIMEOUT' if absolute else 'RESEARCH_LEASE_EXPIRED'
            final='partial' if payload.get('candidates') else 'failed' if absolute else 'interrupted'
            payload.update(error=code,error_origin='queue' if status=='queued' else 'deadline' if absolute else 'lease',
                           outcome='partial_results' if payload.get('candidates') else 'queue_timeout' if status=='queued' else 'timeout',phase='complete')
            db.execute('UPDATE research_jobs SET status=?,payload=?,token=NULL,lease_until=NULL,updated_at=? WHERE id=?',
                       (final,json.dumps(payload,ensure_ascii=False),now,identity))

    @staticmethod
    def _public_view(db,owner,job):
        from backend.knowledge import document_is_public, own_synced_case
        account=job['account_id']
        for item in job['items']:
            row=None
            if item.get('document_id') and item.get('version'):
                row=db.execute('SELECT v.metadata FROM knowledge_versions v JOIN knowledge_documents d ON d.id=v.document_id WHERE d.owner=? AND d.account_id=? AND d.id=? AND v.version=?',
                               (owner,account,item['document_id'],item['version'])).fetchone()
            if row:
                candidates=[json.loads(row[0])]
            else:
                # Failed/old items may only retain a source URL, including in cached reports.
                url=item.get('url') or item.get('source_url')
                candidates=[json.loads(r[0]) for r in db.execute('SELECT v.metadata FROM knowledge_versions v JOIN knowledge_documents d ON d.id=v.document_id WHERE d.owner=? AND d.account_id=?',(owner,account))
                            if json.loads(r[0]).get('source_url')==url] if url else []
            if any(own_synced_case(meta) and not document_is_public(db,owner,account,meta,meta.get('source_url','')) for meta in candidates):
                # Do not rewrite stored audit text; suppress the entire potentially mixed report.
                return {**job,'items':[],'reads':[],'documents':[],'document_ids':[],
                        'attempts':[],'searches':[],'report':None,'error':'SOURCE_VISIBILITY_CHANGED',
                        'source_visibility_blocked':True}
        return job

    def get(self, owner, identity):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE'); self._expire(db)
            return self._public_view(db,owner,self._get(db, owner, identity))

    def list(self, owner, account_id):
        find_account(Operations(self.store).read(owner), account_id)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE'); self._expire(db)
            ids = db.execute('SELECT id FROM research_jobs WHERE owner=? AND account_id=? ORDER BY created_at DESC LIMIT 30', (owner, account_id)).fetchall()
            return [self._public_view(db,owner,self._get(db, owner, row[0])) for row in ids]

    def cancel(self, owner, identity):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            job = self._get(db, owner, identity)
            if job['status'] not in TERMINAL:
                payload=json.loads(db.execute('SELECT payload FROM research_jobs WHERE id=? AND owner=?',(identity,owner)).fetchone()[0])
                payload.update(outcome='cancelled',phase='complete')
                db.execute("UPDATE research_jobs SET status='cancelled',payload=?,token=NULL,lease_until=NULL,updated_at=? WHERE id=? AND owner=?", (json.dumps(payload,ensure_ascii=False),time.time(), identity, owner))
            return self._public_view(db,owner,self._get(db, owner, identity))

    def export(self, owner, identity):
        job = self.get(owner, identity)
        require(not job.get('source_visibility_blocked'),'RESOURCE_NOT_FOUND','报告包含当前不可访问的本人笔记，已停止导出')
        if job['report'] is not None:
            return job['report']
        require(job['status'] in TERMINAL, 'INVALID_TRANSITION', '任务仍在执行，请完成或取消后导出')
        # Interrupted/cancelled work is reviewable without ever replaying search.
        references=[{'document_id':item['document_id'],'version':item['version']} for item in job['items'] if item['status']=='saved']
        report = self.cases.export_versions(owner, job['account_id'], references, title='未完成的资料研究')
        report['content'] += '\n\n任务状态：'+safe(job['status'])+'；未自动重发任何搜索请求。\n'
        report['content'] += '已保存资料使用本次任务的冻结版本；移除不改变历史报告，也不恢复新检索。\n'
        report['content'] += self._scope_report(job)
        return report

    @staticmethod
    def _scope_report(payload):
        lines = ['', '## 任务范围与读取记录', '', '关键词：'+safe('；'.join(payload['queries'])),
                 '搜索服务：'+safe(payload['provider'])+'；范围：'+safe('、'.join(payload['targets'])),
                 '最多读取 6 个网页、保存 3 篇正文；未读取线索不进入正文检索。热度未知，不声明爆款。', '']
        for attempt in payload['attempts']:
            lines.append('- 搜索 '+safe(attempt['query'])+'：'+safe(attempt['status'])+
                         ('；'+safe(attempt['error']) if attempt.get('error') else ''))
        for item in payload['items']:
            lines.append('- '+safe(item['title'])+'：'+safe(item['url'])+'；'+safe(item['status'])+
                         ('；'+safe(item['error']) if item.get('error') else ''))
        return '\n'.join(lines)

    def _claim(self):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE'); self._expire(db)
            row = db.execute("SELECT id,owner FROM research_jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return None
            token = str(uuid4());now=time.time()
            payload=json.loads(db.execute('SELECT payload FROM research_jobs WHERE id=?',(row[0],)).fetchone()[0])
            payload.update(run_started_at=now,deadline_at=now+TASK_SECONDS,phase='starting')
            db.execute("UPDATE research_jobs SET status='running',payload=?,token=?,lease_until=?,updated_at=? WHERE id=? AND status='queued'", (json.dumps(payload,ensure_ascii=False),token,now+LEASE_SECONDS,now,row[0]))
            return dict(id=row[0], owner=row[1], token=token)

    def _guard(self, db, job):
        row = db.execute('SELECT status,token,lease_until,payload FROM research_jobs WHERE id=? AND owner=?', (job['id'], job['owner'])).fetchone()
        require(row and row[0] == 'running' and row[1] == job['token'] and row[2] > time.time(),
                'RESEARCH_STOPPED', '任务已取消或执行租约已失效；不保存迟到结果')
        payload=json.loads(row[3])
        require(payload.get('deadline_at',time.time()+TASK_SECONDS)>time.time(),'RESEARCH_TIMEOUT','研究总时限已到，保留已取得候选')
        return payload

    def _write(self, db, job, payload):
        db.execute('UPDATE research_jobs SET payload=?,lease_until=?,updated_at=? WHERE id=? AND owner=? AND token=?',
                   (json.dumps(payload, ensure_ascii=False), min(time.time()+LEASE_SECONDS,payload.get('deadline_at',time.time()+LEASE_SECONDS)), time.time(), job['id'], job['owner'], job['token']))

    def _change(self, job, mutate=lambda payload: None):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            payload = self._guard(db, job); mutate(payload); self._write(db, job, payload)
            return payload

    def _item(self, job, value):
        return self._change(job, lambda payload: payload['items'].append(value))

    @staticmethod
    def _failure(error):
        # Provider exception strings can contain URLs, credentials or raw bodies.
        return error.code if isinstance(error, DomainError) else 'SOURCE_UNAVAILABLE'

    def once(self):
        job = self._claim()
        if not job:
            return False
        try:
            self._execute(job)
        except Exception as exc:
            if isinstance(exc, DomainError) and exc.code == 'RESEARCH_STOPPED':
                return True
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT status,token,payload FROM research_jobs WHERE id=? AND owner=?',(job['id'],job['owner'])).fetchone()
                if not row or row[0]!='running' or row[1]!=job['token']:return True
                payload=json.loads(row[2]);code=self._failure(exc)
                payload.update(error=code,phase='complete',
                    error_origin='deadline' if 'TIMEOUT' in code and code.startswith('RESEARCH') else payload.get('error_origin') or 'connector',
                    outcome='partial_results' if payload.get('candidates') else 'timeout' if 'TIMEOUT' in code else 'search_failed')
                status='partial' if payload.get('candidates') else 'failed'
                db.execute('UPDATE research_jobs SET status=?,payload=?,token=NULL,lease_until=NULL,updated_at=? WHERE id=?',
                           (status,json.dumps(payload,ensure_ascii=False),time.time(),job['id']))
        return True

    @staticmethod
    def _merge_attempts(payload, attempts):
        for attempt in attempts:
            key=(attempt.get('phase','detail' if attempt.get('note_id') else 'search'),attempt.get('query'),attempt.get('note_id'),attempt.get('attempt',1),attempt.get('status'))
            if not any((a.get('phase','detail' if a.get('note_id') else 'search'),a.get('query'),a.get('note_id'),a.get('attempt',1),a.get('status'))==key for a in payload['attempts']):
                payload['attempts'].append(attempt)

    def _progress(self, job, event):
        allowed=('phase','query','note_id','attempt','status','error','error_origin','mcp_http_status','raw_count','parsed_count','filtered_count','results','sort_scope')
        clean={k:event[k] for k in allowed if k in event}
        clean['counts']={k:v for k,v in event.get('counts',{}).items() if type(v) is int and v>=0}
        def mutate(payload):
            payload['phase']=clean.get('phase',payload.get('phase'))
            payload.setdefault('counts',{}).update(clean['counts'])
            trace=payload.setdefault('trace',[])
            if not trace or {k:v for k,v in trace[-1].items() if k!='at'}!=clean:
                trace.append({**clean,'at':time.time()});payload['trace']=trace[-50:]
            if clean.get('error'):
                payload['error_origin']=clean.get('error_origin',clean.get('phase'))
                payload['mcp_http_status']=clean.get('mcp_http_status')
            if clean.get('phase') in ('search','detail') and clean.get('status') in ('done','failed'):
                self._merge_attempts(payload,[dict(clean)])
        self._change(job,mutate)

    @staticmethod
    def _result(payload):
        counts=payload.setdefault('counts',{})
        counts.update(candidate_count=len(payload.get('candidates',[])),importable_count=sum(c.get('importable',True) for c in payload.get('candidates',[])))
        searches={}
        for a in payload['attempts']:
            if not a.get('note_id') and a.get('phase','search')=='search':searches[a.get('query')]=a
        failed_search=any(a.get('status')=='failed' for a in searches.values())
        failed_details=counts.get('detail_failed_count',0) or sum(i.get('status')=='failed' for i in payload['items'])
        has_results=bool(payload.get('candidates') or payload.get('document_ids'))
        if has_results:return ('partial','partial_results') if failed_search or failed_details else ('done','candidates_ready')
        if failed_search:return 'failed','search_failed'
        if failed_details:return 'failed','detail_failed'
        raw=counts.get('raw_count',sum(a.get('results',a.get('raw_count',0)) for a in searches.values()))
        parsed=counts.get('parsed_count',len(payload['items']))
        if raw and not parsed:return 'failed','invalid_results'
        if raw and counts.get('filtered_count',0)>=parsed:return 'done','filtered_all'
        if payload['items']:return 'partial','unreadable_results'
        return 'done','empty_results'

    def _execute(self, job):
        payload = self._change(job)
        if payload['provider'] == 'xhs_local':
            return self._execute_xhs(job, payload)
        candidates, seen = [], set()
        for query in payload['queries']:
            self._change(job, lambda p: p['attempts'].append({'query': query, 'status': 'started'}))
            try:
                result = self.searcher.search(job['owner'], query, payload['provider'], payload['targets'])
            except Exception as exc:
                code = self._failure(exc)
                self._change(job, lambda p: p['attempts'][-1].update(status='failed', error=code))
                continue
            self._change(job, lambda p: p['attempts'][-1].update(status='done', results=len(result.get('results', []))))
            for source in result.get('results', [])[:8]:
                try:
                    url = public_url(source.get('url'))
                except DomainError:
                    continue
                # URL fragments do not identify different article bodies.
                url = url.split('#', 1)[0]
                if url in seen:
                    continue
                seen.add(url)
                candidates.append({'url': url, 'title': str(source.get('title') or '搜索线索')[:200],
                                   'query': query, 'status': 'lead', 'body_read': False,
                                   'heat': None, 'source_type': 'search_result'})
        pages = 0
        for candidate in candidates:
            current = self._change(job)
            if pages >= 6 or len(current['document_ids']) + len(current.get('candidates', [])) >= 3:
                self._item(job, {**candidate, 'status': 'limit_reached'})
                continue
            try:
                require_readable_source(candidate['url'])
            except DomainError as exc:
                self._item(job, {**candidate, 'status': 'permission_required', 'error': exc.code})
                continue
            pages += 1
            self._change(job)
            try:
                article = self.reader(candidate['url'])
                self._change(job)
                if payload.get('confirmation_required'):
                    packet = dict(account_id=payload['account_id'], title=article['title'], text=article['text'],
                        source_url=article['url'], platform='public_web', content_kind='text',
                        evidence_role=payload['evidence_role'], permission_confirmed=True,
                        published_at=article.get('published_at'), observed_at=article['fetched_at'])
                    self._stage(job, packet, 'read_public_web', None, article['fetched_at'])
                    continue
                def saved(db, identity, version):
                    updated = self._guard(db, job)
                    updated['document_ids'].append(identity)
                    updated['items'].append({**candidate, 'status': 'saved', 'body_read': True,
                                             'document_id': identity, 'version': version})
                    self._write(db, job, updated)
                self.cases.from_article(job['owner'], payload['account_id'], article,
                    evidence_role=payload['evidence_role'], permission_confirmed=True,
                    transaction_guard=lambda db: self._guard(db, job), transaction_saved=saved)
            except Exception as exc:
                if isinstance(exc, DomainError) and exc.code == 'RESEARCH_STOPPED':
                    raise
                self._item(job, {**candidate, 'status': 'failed', 'error': self._failure(exc)})
        current = self._change(job)
        if current.get('candidates'):
            return self._await_confirmation(job)
        report = self.cases.export_versions(job['owner'], payload['account_id'], [{'document_id':i['document_id'],'version':i['version']} for i in current['items'] if i['status']=='saved'], title='本次资料研究')
        report['content'] += '\n'+self._scope_report(current)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE'); final = self._guard(db, job)
            final['report'] = report
            saved_count = len(final['document_ids'])
            incomplete = any(a['status'] != 'done' for a in final['attempts']) or any(i['status'] not in ('saved', 'limit_reached') for i in final['items'])
            status,outcome=self._result(final)
            final.update(outcome=outcome,phase='complete')
            self._write(db, job, final)
            db.execute('UPDATE research_jobs SET status=?,token=NULL,lease_until=NULL WHERE id=?', (status, job['id']))

    def _execute_xhs(self, job, payload):
        from backend.xhs_research import XHSResearch
        research=XHSResearch(self.store)
        def staged(note):
            packet = dict(note)
            provenance = packet.pop('_provenance', None)
            self._stage(job, packet, 'local_browser_public_note',
                        {**(provenance or {}), 'binding_source_id':research.expected_source_id}, packet['observed_at'])
        notes, attempts = research.collect(job['owner'], payload['account_id'], payload['queries'],
            check=lambda:self._change(job), on_note=staged,on_progress=lambda event:self._progress(job,event),
            **({'style_filters':payload['style_filters']} if payload.get('style_filters') else {}))
        self._change(job, lambda p:self._merge_attempts(p,attempts))
        current=self._change(job)
        if current.get('candidates'):
            return self._await_confirmation(job)
        report=self.cases.export_versions(job['owner'],payload['account_id'],[{'document_id':i['document_id'],'version':i['version']} for i in current['items'] if i['status']=='saved'],title='小红书公开案例文字研究')
        report['content'] += '\n'+self._scope_report(current)+'\n\n只读取公开笔记文字及可见互动；没有下载、观看或转写视频。有限搜索结果，不代表全平台爆款排名。\n'
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');final=self._guard(db,job)
            final['report']=report
            self._write(db,job,final)
            status,outcome=self._result(final)
            final.update(outcome=outcome,phase='complete')
            self._write(db,job,final)
            db.execute("UPDATE research_jobs SET status=?,token=NULL,lease_until=NULL WHERE id=?",(status,job['id']))

    def _stage(self, job, packet, method, provenance, fetched_at):
        packet = dict(packet)
        preview = {key:packet.pop(key) for key in ('note_id','content_type','cover_url','body_kind','video_url','metric_display') if key in packet}
        provenance = {**(provenance or {}), **preview}
        importable = (isinstance(packet.get('text'), str) and len(packet['text'].strip()) >= 10
                      and preview.get('body_kind') not in ('summary','lead','unread')
                      and packet.get('content_kind') != 'lead')
        candidate = dict(id=str(uuid4()), packet=packet, source_method=method,
                         provenance=provenance, preview=preview, importable=importable, fetched_at=fetched_at)
        def stage(payload):
            if any(self._candidate_key(c) == self._candidate_key(candidate) for c in payload.get('candidates', [])):
                return
            payload.setdefault('candidates', []).append(candidate)
            payload['items'].append(dict(url=packet['source_url'], title=packet['title'],
                                         status='awaiting_confirmation' if importable else 'unreadable', body_read=importable,
                                         observed_at=packet.get('observed_at'),candidate_id=candidate['id']))
        self._change(job, stage)

    @staticmethod
    def _candidate_key(candidate):
        from backend.knowledge import public_note_id
        packet = candidate['packet']
        note_id = candidate.get('preview', {}).get('note_id') or candidate.get('provenance', {}).get('note_id')
        if packet.get('platform') == 'xiaohongshu':
            return ('xiaohongshu', note_id or public_note_id(packet.get('source_url', '')) or packet.get('source_url'))
        return (packet.get('platform'), packet.get('source_url'))

    def _existing_candidate(self, db, owner, account, candidate):
        key = self._candidate_key(candidate)
        rows = db.execute("SELECT d.id,d.version,d.source_url,v.metadata FROM knowledge_documents d JOIN knowledge_versions v ON v.document_id=d.id AND v.version=d.version WHERE d.owner=? AND d.account_id=? AND d.status='active' AND d.source_type='research_case'", (owner,account))
        for row in rows:
            case = json.loads(row[3]).get('research_case', {})
            prior = {'packet':{'source_url':row[2], 'platform':case.get('platform')}, 'provenance':case.get('provenance',{})}
            if self._candidate_key(prior) == key:
                return row[0], row[1]
        return None

    def _await_confirmation(self, job):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            payload = self._guard(db, job)
            status,outcome=self._result(payload)
            payload.update(outcome=outcome,phase='complete')
            if status=='done':payload.update(error_origin=None,mcp_http_status=None)
            self._write(db, job, payload)
            db.execute("UPDATE research_jobs SET status='awaiting_confirmation',token=NULL,lease_until=NULL WHERE id=?", (job['id'],))

    def confirm(self, owner, identity, data):
        require(isinstance(data, dict) and set(data)=={'candidate_ids','key'} and
                isinstance(data['key'], str) and 1<=len(data['key'])<=160 and
                isinstance(data['candidate_ids'], list) and 1<=len(data['candidate_ids'])<=3 and
                all(isinstance(i,str) and i for i in data['candidate_ids']) and
                len(set(data['candidate_ids']))==len(data['candidate_ids']),
                'INVALID_INPUT', '请选择需要保存的资料并提供确认编号')
        selection=sorted(data['candidate_ids'])
        scoped = self.get(owner, identity)
        find_account(Operations(self.store).read(owner), scoped['account_id'])
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            job=self._get(db,owner,identity)
            prior=job.get('confirmation')
            if prior:
                require(prior['key']==data['key'] and prior['candidate_ids']==selection,
                        'IDEMPOTENCY_CONFLICT','确认选择已经提交，不能改用其他资料')
                if job['status']=='done':return self._public_view(db,owner,job)
            require(job['status'] in ('awaiting_confirmation','confirming','cancelled','partial','interrupted','failed'), 'INVALID_TRANSITION','任务当前不能确认')
            chosen={c['id']:c for c in job.get('candidates',[])}
            require(set(selection)<=set(chosen),'INVALID_INPUT','候选资料不存在')
            require(all(chosen[i].get('importable', bool(chosen[i]['packet'].get('text','').strip())) and
                        len(chosen[i]['packet'].get('text','').strip()) >= 10 for i in selection),
                    'CANDIDATE_UNREADABLE','所选资料尚无可用正文，不能加入知识库')
            payload={k:job[k] for k in job if k not in ('id','status','created_at','updated_at','documents','searches','reads')}
            payload['confirmation']={'key':data['key'],'candidate_ids':selection}
            db.execute("UPDATE research_jobs SET status='confirming',payload=?,updated_at=? WHERE id=? AND owner=?",
                       (json.dumps(payload,ensure_ascii=False),time.time(),identity,owner))
        for candidate_id in selection:
            with self.store.connect() as db:
                current=self._get(db,owner,identity)
            if any(i.get('candidate_id')==candidate_id and i['status']=='saved' for i in current['items']):continue
            candidate=chosen[candidate_id]
            packet=dict(candidate['packet'])
            provenance={**(candidate.get('provenance') or {}),'human_confirmed':True,'confirmation_job_id':identity}
            def guard(db):
                row=db.execute('SELECT status,payload FROM research_jobs WHERE id=? AND owner=?',(identity,owner)).fetchone()
                require(row is not None,'RESOURCE_NOT_FOUND','研究任务不可访问')
                value=json.loads(row[1])
                require(value.get('confirmation')=={'key':data['key'],'candidate_ids':selection},'IDEMPOTENCY_CONFLICT','确认范围已改变')
                require(not any(i.get('candidate_id')==candidate_id and i['status']=='saved' for i in value['items']), 'RESEARCH_CANDIDATE_SAVED','资料已经保存')
                require(row[0]=='confirming','RESEARCH_STOPPED','确认已取消，不保存迟到结果')
                if candidate['source_method'].startswith('local_browser'):
                    from backend.xhs_research import XHSResearch
                    research=XHSResearch(self.store)
                    research.expected_source_id=candidate.get('provenance',{}).get('binding_source_id')
                    research.guard_save(db,owner,job['account_id'])
                return value
            def saved(db, document_id, version):
                value=guard(db)
                if document_id not in value['document_ids']:value['document_ids'].append(document_id)
                for item in value['items']:
                    if item.get('candidate_id')==candidate_id:item.update(status='saved',document_id=document_id,version=version)
                db.execute('UPDATE research_jobs SET payload=?,updated_at=? WHERE id=? AND owner=?',
                           (json.dumps(value,ensure_ascii=False),time.time(),identity,owner))
            def unique_guard(db):
                guard(db)
                require(self._existing_candidate(db,owner,job['account_id'],candidate) is None,
                        'RESEARCH_ALREADY_EXISTS','该笔记已入库，复用已有版本')
            try:
                try:
                    # The check runs within Knowledge's write transaction, so concurrent
                    # confirmations cannot create a second copy with a refreshed URL token.
                    self.cases.save(owner,packet,source_method=candidate['source_method'],fetched_at=candidate['fetched_at'],
                                    provenance=provenance,transaction_guard=unique_guard,transaction_saved=saved)
                except DomainError as exc:
                    if exc.code != 'RESEARCH_ALREADY_EXISTS':raise
                    with self.store.connect() as db:
                        db.execute('BEGIN IMMEDIATE');guard(db)
                        existing=self._existing_candidate(db,owner,job['account_id'],candidate)
                        require(existing is not None,'VERSION_CONFLICT','已有资料已移除，请重试')
                        saved(db,*existing)
            except DomainError as exc:
                if exc.code != 'RESEARCH_CANDIDATE_SAVED':raise
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current=self._get(db,owner,identity)
            if current['status']=='done':return self._public_view(db,owner,current)
            require(current['status']=='confirming','RESEARCH_STOPPED','确认已取消')
            payload=json.loads(db.execute('SELECT payload FROM research_jobs WHERE id=? AND owner=?',(identity,owner)).fetchone()[0])
            for item in payload['items']:
                if item['status']=='awaiting_confirmation':item['status']='not_selected'
            payload['report']=None
            db.execute("UPDATE research_jobs SET status='done',payload=?,updated_at=? WHERE id=? AND owner=?",
                       (json.dumps(payload,ensure_ascii=False),time.time(),identity,owner))
            return self._public_view(db,owner,self._get(db,owner,identity))

    @staticmethod
    def _same_xhs_case(full,note):
        """Observation time alone is a job event, not a new content version."""
        case=full['metadata'].get('research_case',{})
        return (full['fingerprint']==hashlib.sha256(note['text'].strip().encode()).hexdigest()
                and full['title']==note['title'].strip() and full['source_url']==note['source_url']
                and case.get('source_method') in ('local_browser_video_description','local_browser_public_note')
                and all(case.get(k)==note.get(k) for k in ('metrics','published_at','content_kind','evidence_role'))
                and all(case.get(k)==note.get(k,'').strip() for k in ('platform','author')))

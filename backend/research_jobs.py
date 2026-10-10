"""Bounded durable research; interrupted paid searches are never replayed."""
import json
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
TERMINAL = ('done', 'partial', 'failed', 'interrupted', 'cancelled')


class ResearchJobs:
    def __init__(self, store, searcher=None, reader=None, cases=None):
        self.store = store
        self.searcher = searcher or SearchSettings(store)
        self.reader = reader or read_article
        self.cases = cases or ResearchCases(store)

    def create(self, owner, data):
        fields = {'account_id', 'queries', 'provider', 'targets', 'evidence_role', 'permission_confirmed', 'key'}
        require(isinstance(data, dict) and set(data) == fields, 'INVALID_INPUT', '研究任务字段无效')
        require(isinstance(data['key'], str) and 1 <= len(data['key']) <= 160,
                'INVALID_INPUT', '请提供任务幂等编号')
        queries = data['queries']
        require(isinstance(queries, list) and 1 <= len(queries) <= 2 and
                all(isinstance(q, str) and 2 <= len(q.strip()) <= 120 for q in queries),
                'INVALID_INPUT', '研究任务限 1 至 2 个搜索词，每个 2 至 120 字符')
        require(data['provider'] in ('bing', 'wikipedia', 'baidu'), 'INVALID_INPUT', '搜索服务无效')
        domains = target_domains(data['targets'])
        require(data['provider'] != 'wikipedia' or not domains, 'INVALID_INPUT', '百科仅支持全网范围')
        require(data['evidence_role'] in ('expression_reference', 'product_fact') and
                data['permission_confirmed'] is True, 'INVALID_INPUT', '请选择资料用途并确认保存权限')
        find_account(Operations(self.store).read(owner), data['account_id'])
        fingerprint = digest(data)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT id,fingerprint FROM research_jobs WHERE owner=? AND key=?', (owner, data['key'])).fetchone()
            if prior:
                require(prior[1] == fingerprint, 'IDEMPOTENCY_CONFLICT', '相同任务编号不能提交不同研究范围')
                return self._get(db, owner, prior[0])
            self._expire(db)
            count = db.execute("SELECT COUNT(*) FROM research_jobs WHERE owner=? AND status IN ('queued','running')", (owner,)).fetchone()[0]
            require(count < 3, 'QUOTA_EXCEEDED', '最多同时保留 3 个待执行研究任务')
            identity, now = str(uuid4()), time.time()
            payload = {k: data[k] for k in fields - {'key'}}
            payload.update(queries=list(dict.fromkeys(q.strip() for q in queries)), attempts=[], items=[],
                           document_ids=[], report=None, error=None,
                           limits={'max_queries': 2, 'max_pages': 6, 'max_documents': 3})
            db.execute('INSERT INTO research_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (identity, owner, data['account_id'], data['key'], fingerprint, 'queued',
                        json.dumps(payload, ensure_ascii=False), None, None, now, now))
            return self._get(db, owner, identity)

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
        db.execute("UPDATE research_jobs SET status='interrupted',token=NULL,lease_until=NULL,updated_at=? WHERE status='running' AND lease_until<=?", (time.time(), time.time()))

    def get(self, owner, identity):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE'); self._expire(db)
            return self._get(db, owner, identity)

    def list(self, owner, account_id):
        find_account(Operations(self.store).read(owner), account_id)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE'); self._expire(db)
            ids = db.execute('SELECT id FROM research_jobs WHERE owner=? AND account_id=? ORDER BY created_at DESC LIMIT 30', (owner, account_id)).fetchall()
            return [self._get(db, owner, row[0]) for row in ids]

    def cancel(self, owner, identity):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            job = self._get(db, owner, identity)
            if job['status'] not in TERMINAL:
                db.execute("UPDATE research_jobs SET status='cancelled',token=NULL,lease_until=NULL,updated_at=? WHERE id=? AND owner=?", (time.time(), identity, owner))
            return self._get(db, owner, identity)

    def export(self, owner, identity):
        job = self.get(owner, identity)
        if job['report'] is not None:
            return job['report']
        require(job['status'] in TERMINAL, 'INVALID_TRANSITION', '任务仍在执行，请完成或取消后导出')
        # Interrupted/cancelled work is reviewable without ever replaying search.
        active = {doc['id'] for doc in self.cases.list(owner, job['account_id'])}
        available = [identity for identity in job['document_ids'] if identity in active]
        report = self.cases.export(owner, job['account_id'], available, title='未完成的资料研究')
        report['content'] += '\n\n任务状态：'+safe(job['status'])+'；未自动重发任何搜索请求。\n'
        report['content'] += '已保存资料使用导出时仍有效的版本；停用资料不重新导出。\n'
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
            token = str(uuid4())
            db.execute("UPDATE research_jobs SET status='running',token=?,lease_until=?,updated_at=? WHERE id=? AND status='queued'", (token, time.time()+LEASE_SECONDS, time.time(), row[0]))
            return dict(id=row[0], owner=row[1], token=token)

    def _guard(self, db, job):
        row = db.execute('SELECT status,token,lease_until,payload FROM research_jobs WHERE id=? AND owner=?', (job['id'], job['owner'])).fetchone()
        require(row and row[0] == 'running' and row[1] == job['token'] and row[2] > time.time(),
                'RESEARCH_STOPPED', '任务已取消或执行租约已失效；不保存迟到结果')
        return json.loads(row[3])

    def _write(self, db, job, payload):
        db.execute('UPDATE research_jobs SET payload=?,lease_until=?,updated_at=? WHERE id=? AND owner=? AND token=?',
                   (json.dumps(payload, ensure_ascii=False), time.time()+LEASE_SECONDS, time.time(), job['id'], job['owner'], job['token']))

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
                try:
                    payload = self._guard(db, job)
                except DomainError:
                    return True
                payload['error'] = self._failure(exc)
                self._write(db, job, payload)
                db.execute("UPDATE research_jobs SET status='interrupted',token=NULL,lease_until=NULL WHERE id=?", (job['id'],))
        return True

    def _execute(self, job):
        payload = self._change(job)
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
            if pages >= 6 or len(current['document_ids']) >= 3:
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
        report = self.cases.export(job['owner'], payload['account_id'], current['document_ids'], title='本次资料研究')
        report['content'] += '\n'+self._scope_report(current)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE'); final = self._guard(db, job)
            final['report'] = report
            saved_count = len(final['document_ids'])
            incomplete = any(a['status'] != 'done' for a in final['attempts']) or any(i['status'] not in ('saved', 'limit_reached') for i in final['items'])
            status = ('partial' if incomplete else 'done') if saved_count else ('partial' if final['items'] else 'failed')
            self._write(db, job, final)
            db.execute('UPDATE research_jobs SET status=?,token=NULL,lease_until=NULL WHERE id=?', (status, job['id']))

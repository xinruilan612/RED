"""Account-scoped versioned evidence with BM25 and optional real local semantic RAG.

No fake embeddings: local model absence is labelled as lexical-only retrieval.
Original files, page locations and immutable excerpts persist.
"""
import base64
import hashlib
import json
import math
import re
import time
from collections import Counter
from uuid import uuid4
from backend.accounts import find_account
from backend.contracts import require
from backend.demo import validate_text
from backend.operations import Operations

MAX_FILE = 3_000_000
MAX_TEXT = 100_000


def tokens(text):
    result = re.findall(r'[a-z0-9]+',text.lower())
    for word in re.findall(r'[\u3400-\u9fff]+',text):
        result.extend(word[i:i+2] for i in range(len(word)-1))
        if len(word)==1: result.append(word)
    return result


def bm25_scores(query, rows):
    """Score only the caller's authorized, already-filtered chunk rows."""
    wanted=set(tokens(query))
    documents=[(row,json.loads(row[6])) for row in rows]
    n=len(documents);avg=sum(sum(terms.values()) for _,terms in documents)/max(1,n)
    df={term:sum(term in terms for _,terms in documents) for term in wanted}
    scores={}
    for row,terms in documents:
        matched=wanted & terms.keys()
        # A lone accidental bigram in a long question is insufficient evidence.
        if not matched or (len(wanted)>3 and len(matched)<2):continue
        length=sum(terms.values())
        scores[row[0]]=sum(math.log(1+(n-df[term]+0.5)/(df[term]+0.5))*(terms[term]*2.2)/
                          (terms[term]+1.2*(.25+.75*length/max(1,avg))) for term in matched)
    return scores


def parse_file(name, data):
    require(isinstance(name,str) and 0<len(name)<=200 and 0<len(data)<=MAX_FILE,'INVALID_INPUT','文件大小需在 3 MB 内')
    suffix=name.rsplit('.',1)[-1].lower()
    if suffix in ('txt','md'):
        try: pages=[(1,data.decode('utf-8-sig'))]
        except UnicodeDecodeError: raise ValueError('请将文本文件保存为 UTF-8') from None
    elif suffix=='pdf':
        import subprocess
        import sys
        from pathlib import Path
        try:
            proc=subprocess.run([sys.executable,'-m','backend.document_parser'],input=data,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=12,cwd=Path(__file__).resolve().parents[1])
            packet=json.loads(proc.stdout)
            require('pages' in packet,'INVALID_INPUT',packet.get('error','无法读取 PDF'))
            pages=packet['pages']
        except (subprocess.TimeoutExpired,ValueError):
            raise ValueError('无法读取 PDF、解析超时或超出限制；扫描件暂不支持 OCR') from None
    elif suffix=='docx':
        import subprocess
        import sys
        from pathlib import Path
        try:
            proc=subprocess.run([sys.executable,'-m','backend.word_parser'],input=data,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=12,cwd=Path(__file__).resolve().parents[1])
            packet=json.loads(proc.stdout)
            require('paragraphs' in packet,'INVALID_INPUT',packet.get('error','无法读取 Word 文档'))
            pages=packet['paragraphs']
        except (subprocess.TimeoutExpired,ValueError):
            raise ValueError('无法读取 DOCX、解析超时或超出限制；请另存为 .docx 后重试') from None
    else:
        raise ValueError('目前支持 UTF-8 TXT、Markdown、文本型 PDF 和 DOCX Word 文档')
    require(sum(len(t) for _,t in pages)<=MAX_TEXT and any(t.strip() for _,t in pages),'INVALID_INPUT','没有可提取文字，或正文超过 10 万字符；扫描件尚不支持 OCR')
    return pages


def chunks(pages):
    result=[]
    for page,text in pages:
        # Keep leading/trailing TABs: DOCX table rows use them for empty cells.
        text=text.replace('\x00','').replace('\r\n','\n').strip(' \r\n')
        for start in range(0,len(text),650):
            excerpt=text[start:start+800]
            if excerpt.strip(): result.append({'page':page,'offset':start,'text':excerpt})
    return result


def evidence_metadata(metadata, document_id, version):
    case=metadata.get('research_case',{})
    return {'content_kind':case.get('content_kind','text'),
            'source_scope':'current_account',
            'body_kind':case.get('provenance',{}).get('body_kind',case.get('content_kind','text')),
            'classification':metadata.get('classification',{}),
            'case_ref':({'document_id':document_id,'version':version,'platform':case.get('platform'),
                         'published_at':case.get('published_at'),'observed_at':case.get('observed_at'),
                         'assessment_status':case.get('assessment',{}).get('status'),
                         'verification':case.get('verification'), 'source_method':case.get('source_method'),
                         'metrics':case.get('metrics',{}), 'provenance':case.get('provenance',{})} if case else None)}


def own_synced_case(metadata):
    return metadata.get('research_case',{}).get('source_method') in ('local_browser_mcp','xhs_own_sync')


def public_note_id(url):
    from urllib.parse import urlsplit
    parsed=urlsplit(url or '')
    if parsed.hostname not in ('www.xiaohongshu.com','xiaohongshu.com'):return None
    match=re.fullmatch(r'/explore/([A-Za-z0-9_-]+)',parsed.path.rstrip('/'))
    return match.group(1) if match else None


def document_is_public(db,owner,account,metadata,url):
    if not own_synced_case(metadata):return True
    from backend.xhs_sync import XHSSync
    return public_note_id(url) in XHSSync.public_note_ids(db,owner,account)


def assert_public_model_evidence(store,run,db,seen=None):
    """Recheck old snapshots before each model call; history remains unchanged."""
    from backend.comment_feedback import assert_visible
    assert_visible(run,db)
    seen=set() if seen is None else seen
    require(run.run_id not in seen,'SOURCE_VISIBILITY_CHANGED','来源任务关系无法确认，历史任务暂不可展示或发送模型')
    seen.add(run.run_id)
    evidence=[source for source in run.context.get('evidence',[]) if source.get('source_type')=='research_case']
    wind=getattr(run,'windtunnel',None) or {}
    wind_sources=wind.get('sources',[])+[source for history in wind.get('source_history',[]) for source in history.get('sources',[])]
    evidence.extend(source for source in wind_sources if source.get('document_id'))
    imported={draft.get('source',{}).get('run_id') for draft in wind.get('drafts',[]) if isinstance(draft.get('source'),dict)}-{None}
    for identity in imported:
        try:origin=store.get(identity,run.owner_id)
        except ValueError:
            require(False,'SOURCE_VISIBILITY_CHANGED','来源任务已无法确认，历史任务暂不可展示或发送模型')
        assert_public_model_evidence(store,origin,db,seen)
    if not evidence:return
    account=run.context.get('operations',{}).get('account_id') or run.context.get('account_id')
    checked=None
    for source in evidence:
        identity,version=source.get('document_id'),source.get('version')
        require(identity and version,'SOURCE_VISIBILITY_CHANGED','来源身份已无法确认，历史任务暂不可展示或发送模型')
        row=db.execute('SELECT v.metadata,d.source_url FROM knowledge_versions v JOIN knowledge_documents d ON d.id=v.document_id WHERE d.id=? AND d.owner=? AND d.account_id=? AND v.version=?',
                       (identity,run.owner_id,account,version)).fetchone()
        require(row is not None,'SOURCE_VISIBILITY_CHANGED','来源版本已无法确认，历史任务暂不可展示或发送模型')
        metadata=json.loads(row[0])
        if not own_synced_case(metadata):continue
        if checked is None:
            from backend.xhs_sync import XHSSync
            checked=XHSSync.public_note_ids(db,run.owner_id,account)
        require(public_note_id(metadata.get('source_url',source.get('url',row[1]))) in checked,'SOURCE_VISIBILITY_CHANGED',
                '本人笔记当前未核实为公开，历史任务内容已隐藏且停止模型调用；请使用公开资料创建新任务')


def style_case(metadata):
    case=metadata.get('research_case',{})
    provenance=case.get('provenance',{})
    metrics=case.get('metrics',{})
    selection=provenance.get('style_selection',{})
    thresholds=all(type(selection.get('min_'+key)) is int and selection['min_'+key]>0 for key in ('likes','favorites'))
    return (metadata.get('retrieval_eligible',True) and not case.get('review_required')
            and case.get('content_kind')!='lead' and case.get('evidence_role')=='expression_reference'
            and case.get('source_method')=='local_browser_public_note'
            and provenance.get('visibility')=='public' and provenance.get('visibility_source')=='platform_search_result'
            and provenance.get('style_library_eligible') is True
            and thresholds and any(type(metrics.get(key)) is int and metrics[key]>=selection['min_'+key] for key in ('likes','favorites')))


class Knowledge:
    def __init__(self, store, embedding_provider=None, use_configured_embeddings=True):
        self.store=store
        self.embedding_provider=embedding_provider
        self.use_configured_embeddings=use_configured_embeddings
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, account_id TEXT NOT NULL,
                    title TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL,
                    source_type TEXT NOT NULL, source_url TEXT NOT NULL, updated_at BIGINT NOT NULL);
                CREATE INDEX IF NOT EXISTS knowledge_scope ON knowledge_documents(owner,account_id,status);
                CREATE TABLE IF NOT EXISTS knowledge_versions (
                    document_id TEXT NOT NULL REFERENCES knowledge_documents(id), version INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL, original_base64 TEXT NOT NULL, filename TEXT NOT NULL,
                    metadata TEXT NOT NULL, PRIMARY KEY(document_id,version));
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL, version INTEGER NOT NULL,
                    page INTEGER NOT NULL, offset_start INTEGER NOT NULL, text TEXT NOT NULL, terms TEXT NOT NULL,
                    FOREIGN KEY(document_id,version) REFERENCES knowledge_versions(document_id,version));
                CREATE INDEX IF NOT EXISTS knowledge_chunk_version ON knowledge_chunks(document_id,version);
                CREATE TABLE IF NOT EXISTS retrieval_events (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, account_id TEXT NOT NULL,
                    query TEXT NOT NULL, source_ids TEXT NOT NULL, created_at BIGINT NOT NULL);
            ''')
            db.execute('INSERT INTO schema_migrations VALUES(2,?) ON CONFLICT(version) DO NOTHING',('2026-09-21',))

    def account(self, owner, account_id):
        return find_account(Operations(self.store).read(owner),account_id)

    def preview(self, owner, data):
        from backend.document_input import INPUT_FIELDS, preview
        require(isinstance(data,dict) and set(data)<=INPUT_FIELDS,'INVALID_INPUT','资料预览字段无效')
        self.account(owner,data.get('account_id'))
        validate_text(data.get('title'),'资料标题',200)
        if data.get('document_id'):
            existing=self.get(owner,data['account_id'],data['document_id'])
            require(existing['version']==data.get('expected_version'),'VERSION_CONFLICT','资料已更新，请重新选择版本')
            require(existing['source_type']!='research_case','CASE_EDIT_REQUIRED','研究案例请使用案例专用编辑入口')
        return preview(data)

    def save(self, owner, data, source_type='text', source_url='', metadata=None, *, transaction_guard=None, transaction_saved=None):
        from backend.document_input import INPUT_FIELDS, read_input, reviewed_pages
        require(isinstance(data,dict) and set(data)<=INPUT_FIELDS|{'input_review'},'INVALID_INPUT','资料字段无效')
        account=data.get('account_id');self.account(owner,account)
        title=validate_text(data.get('title'),'资料标题',200)
        name,raw,pages=read_input(data)
        if 'file_base64' in data:source_type='upload'
        review=None
        if 'input_review' in data:
            require(source_type in ('text','upload'),'INVALID_INPUT','案例资料不能通过普通文档校对保存')
            pages,review=reviewed_pages(data,raw,pages)
        parts=chunks(pages)
        fingerprint=hashlib.sha256(raw).hexdigest();now=int(time.time())
        identity=data.get('document_id') or str(uuid4())
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if transaction_guard is not None: transaction_guard(db)
            if review:
                # Short writes are serialized on both supported databases. A
                # repeated uncertain confirmation must not create another version.
                receipts=db.execute('SELECT d.id,v.version,v.metadata FROM knowledge_versions v JOIN knowledge_documents d ON d.id=v.document_id WHERE d.owner=? AND d.account_id=? AND v.metadata LIKE ?',
                                    (owner,account,'%'+review['confirmation_id']+'%')).fetchall()
                for saved_id,saved_version,saved_meta in receipts:
                    receipt=json.loads(saved_meta).get('input_review',{})
                    if receipt.get('confirmation_id')==review['confirmation_id']:
                        require(receipt.get('request_sha256')==review['request_sha256'],'VERSION_CONFLICT','确认请求已变化，请重新预览；先前保存的资料保留')
                        result=self._get(db,owner,account,saved_id)
                        result['input_confirmation']={**receipt,'document_id':saved_id,
                            'confirmed_version':saved_version,'current_version':result['version'],'replayed':True}
                        return result
            row=db.execute('SELECT version,status,source_type FROM knowledge_documents WHERE id=? AND owner=? AND account_id=?',(identity,owner,account)).fetchone()
            if data.get('document_id'):
                require(row and row[1]=='active','RESOURCE_NOT_FOUND','资料不可访问')
                require(type(data.get('expected_version')) is int and data['expected_version']==row[0],'VERSION_CONFLICT','资料已更新，请刷新')
                require(row[2]!='research_case' or (source_type=='research_case' and isinstance(metadata,dict) and isinstance(metadata.get('research_case'),dict)),
                        'CASE_EDIT_REQUIRED','研究案例必须使用案例专用编辑接口更新，以保留来源、资料用途和未读线索限制')
            else:
                count=db.execute("SELECT COUNT(*) FROM knowledge_documents WHERE owner=? AND account_id=? AND status='active'",(owner,account)).fetchone()[0]
                require(count<100,'QUOTA_EXCEEDED','每账号首版最多 100 份有效资料')
                duplicate=db.execute("SELECT d.id FROM knowledge_documents d JOIN knowledge_versions v ON v.document_id=d.id AND v.version=d.version WHERE d.owner=? AND d.account_id=? AND d.status='active' AND v.fingerprint=?",(owner,account,fingerprint)).fetchone()
                require(not duplicate,'DUPLICATE','当前账号已有相同正文，请更新原资料或直接使用')
            version=row[0]+1 if row else 1
            if row:
                db.execute('UPDATE knowledge_documents SET title=?,version=?,source_type=?,source_url=?,updated_at=? WHERE id=?',(title,version,source_type,source_url,now,identity))
            else:
                db.execute('INSERT INTO knowledge_documents VALUES(?,?,?,?,?,?,?,?,?)',(identity,owner,account,title,version,'active',source_type,source_url,now))
            meta={**(metadata or {}),'title':title,'source_type':source_type,'source_url':source_url,'stored_at':now,
                  'location_type':'paragraph' if name.lower().endswith('.docx') else 'page','page_count':len(pages),
                  'extracted_chars':sum(len(text) for _,text in pages)}
            if review:meta['input_review']={**review,'confirmed_at':now}
            from backend.creation_taxonomy import classify_document
            previous=json.loads(db.execute('SELECT metadata FROM knowledge_versions WHERE document_id=? AND version=?',(identity,row[0])).fetchone()[0]) if row else {}
            requested=data.get('classification', (metadata or {}).get('classification', previous.get('classification')))
            meta['classification']=(previous['classification'] if requested is previous.get('classification') and requested is not None else classify_document(requested,title,' '.join(t for _,t in pages),meta))
            db.execute('INSERT INTO knowledge_versions VALUES(?,?,?,?,?,?)',(identity,version,fingerprint,base64.b64encode(raw).decode(),name,json.dumps(meta,ensure_ascii=False)))
            for part in parts:
                db.execute('INSERT INTO knowledge_chunks VALUES(?,?,?,?,?,?,?)',(str(uuid4()),identity,version,part['page'],part['offset'],part['text'],json.dumps(Counter(tokens(part['text'])),ensure_ascii=False)))
            if transaction_saved is not None: transaction_saved(db,identity,version)
        result=self.get(owner,account,identity)
        if review:
            result['input_confirmation']={**meta['input_review'],'document_id':identity,
                'confirmed_version':version,'current_version':result['version'],'replayed':False}
        return result

    def original(self, owner, account, identity, version):
        document=self.get_version(owner,account,identity,version)
        self.assert_public_document(owner,account,document)
        with self.store.connect() as db:
            row=db.execute('SELECT original_base64 FROM knowledge_versions WHERE document_id=? AND version=?',(identity,version)).fetchone()
        return document['filename'],base64.b64decode(row[0])

    def list(self, owner, account):
        self.account(owner,account)
        with self.store.connect() as db:
            rows=db.execute("SELECT d.id,d.title,d.version,d.source_type,d.source_url,d.updated_at,v.filename,v.metadata FROM knowledge_documents d JOIN knowledge_versions v ON v.document_id=d.id AND v.version=d.version WHERE d.owner=? AND d.account_id=? AND d.status='active' ORDER BY d.updated_at DESC,d.id",(owner,account)).fetchall()
            rows=[r for r in rows if document_is_public(db,owner,account,json.loads(r[7]),r[4])]
        return [dict(zip(('id','title','version','source_type','source_url','updated_at','filename'),r[:7]),metadata=json.loads(r[7])) for r in rows]

    def get(self, owner, account, identity):
        self.account(owner,account)
        with self.store.connect() as db:
            return self._get(db,owner,account,identity)

    def _get(self, db, owner, account, identity):
        row=db.execute("SELECT title,version,source_type,source_url FROM knowledge_documents WHERE owner=? AND account_id=? AND id=? AND status='active'",(owner,account,identity)).fetchone()
        require(row,'RESOURCE_NOT_FOUND','资料不可访问')
        v=db.execute('SELECT fingerprint,metadata,filename FROM knowledge_versions WHERE document_id=? AND version=?',(identity,row[1])).fetchone()
        require(document_is_public(db,owner,account,json.loads(v[1]),row[3]),'RESOURCE_NOT_FOUND','资料当前不可访问')
        parts=db.execute('SELECT id,page,offset_start,text FROM knowledge_chunks WHERE document_id=? AND version=? ORDER BY page,offset_start',(identity,row[1])).fetchall()
        versions=[dict(version=r[0],metadata=json.loads(r[1])) for r in db.execute('SELECT version,metadata FROM knowledge_versions WHERE document_id=? ORDER BY version DESC',(identity,))
                  if document_is_public(db,owner,account,json.loads(r[1]),json.loads(r[1]).get('source_url',''))]
        return dict(id=identity,title=row[0],version=row[1],source_type=row[2],source_url=row[3],fingerprint=v[0],metadata=json.loads(v[1]),filename=v[2],versions=versions,chunks=[dict(zip(('id','page','offset','text'),p),classification=json.loads(v[1]).get('classification',{}),source_url=row[3]) for p in parts])

    def assert_public_document(self,owner,account,document):
        """External exports must recheck privacy even when reading audit versions."""
        with self.store.connect() as db:
            require(document_is_public(db,owner,account,document['metadata'],document['source_url']),
                    'RESOURCE_NOT_FOUND','资料当前不可访问，历史审计不代表可公开导出')

    def get_version(self, owner, account, identity, version):
        """Read an immutable owned version for historical reports, even if removed.

        This is not retrieval: deleted documents remain excluded from new RAG.
        Return neither original file bytes nor unrelated version contents.
        """
        self.account(owner,account)
        require(type(version) is int and version>0,'INVALID_INPUT','资料版本必须为正整数')
        with self.store.connect() as db:
            row=db.execute('SELECT v.fingerprint,v.metadata,v.filename FROM knowledge_versions v JOIN knowledge_documents d ON d.id=v.document_id WHERE d.owner=? AND d.account_id=? AND d.id=? AND v.version=?',(owner,account,identity,version)).fetchone()
            require(row,'RESOURCE_NOT_FOUND','资料版本不可访问')
            parts=db.execute('SELECT id,page,offset_start,text FROM knowledge_chunks WHERE document_id=? AND version=? ORDER BY page,offset_start',(identity,version)).fetchall()
        metadata=json.loads(row[1])
        return dict(id=identity,title=metadata['title'],version=version,source_type=metadata['source_type'],
                    source_url=metadata['source_url'],fingerprint=row[0],metadata=metadata,filename=row[2],
                    chunks=[dict(zip(('id','page','offset','text'),part),classification=metadata.get('classification',{}),source_url=metadata.get('source_url','')) for part in parts])

    def delete(self, owner, account, identity, version):
        self.account(owner,account)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT version FROM knowledge_documents WHERE id=? AND owner=? AND account_id=? AND status='active'",(identity,owner,account)).fetchone()
            require(row,'RESOURCE_NOT_FOUND','资料不可访问')
            require(type(version) is int and row[0]==version,'VERSION_CONFLICT','资料版本已变化')
            db.execute("UPDATE knowledge_documents SET status='deleted' WHERE id=?",(identity,))
        return {'deleted':True,'note':'后续检索已排除；已有任务的证据快照保留审计'}

    def retrieve(self, owner, account, query, limit=4, document_ids=None, *, style_only=False, approved_only=False):
        self.account(owner,account);query=validate_text(query,'检索内容',300)
        require(type(limit) is int and 1<=limit<=20,'INVALID_INPUT','检索条数需为 1–20')
        if document_ids is not None:
            require(isinstance(document_ids,list) and len(document_ids)<=3 and all(isinstance(x,str) and x for x in document_ids),'INVALID_INPUT','最多选择 3 份资料')
            document_ids=list(dict.fromkeys(document_ids))
            if document_ids:
                with self.store.connect() as db:
                    found=db.execute("SELECT id FROM knowledge_documents WHERE owner=? AND account_id=? AND status='active' AND id IN ("+','.join('?' for _ in document_ids)+")",(owner,account,*document_ids)).fetchall()
                require(len(found)==len(document_ids),'RESOURCE_NOT_FOUND','所选资料不属于当前账号或已失效')
        wanted=set(tokens(query))
        with self.store.connect() as db:
            sql="SELECT c.id,c.document_id,c.version,c.page,c.offset_start,c.text,c.terms,d.title,d.source_url,d.source_type,v.filename,v.metadata FROM knowledge_chunks c JOIN knowledge_documents d ON d.id=c.document_id AND d.version=c.version JOIN knowledge_versions v ON v.document_id=c.document_id AND v.version=c.version WHERE d.owner=? AND d.account_id=? AND d.status='active'"
            args=[owner,account]
            if document_ids is not None:
                if not document_ids: return {'engine':'bm25-zh-bigram-v1','query':query,'sources':[],'insufficient':True,'note':'没有选择资料'}
                sql+=' AND d.id IN ('+','.join('?' for _ in document_ids)+')';args.extend(document_ids)
            rows=db.execute(sql,args).fetchall()
        rows=[r for r in rows if json.loads(r[11]).get('retrieval_eligible',True)]
        if any(own_synced_case(json.loads(r[11])) for r in rows):
            from backend.xhs_sync import XHSSync
            with self.store.connect() as db:
                public_ids=XHSSync.public_note_ids(db,owner,account)
            rows=[r for r in rows if not own_synced_case(json.loads(r[11])) or public_note_id(r[8]) in public_ids]
        if approved_only:rows=[r for r in rows if json.loads(r[11]).get('research_case',{}).get('provenance',{}).get('human_confirmed') is True]
        if style_only:rows=[r for r in rows if style_case(json.loads(r[11]))]
        lexical_scores=bm25_scores(query,rows)
        results=[]
        for r in rows:
            if r[0] not in lexical_scores:continue
            score=lexical_scores[r[0]]
            metadata=json.loads(r[11])
            results.append(dict(source_id='kb:'+r[0],document_id=r[1],version=r[2],page=r[3],offset=r[4],text=r[5],title=r[7],url=r[8],source_type=r[9],filename=r[10],location_type=metadata.get('location_type','page'),evidence_role=metadata.get('evidence_role','source_material'),**evidence_metadata(metadata,r[1],r[2]),score=round(score,4),verification='原文片段匹配，来源真实性仍需核查'))
        results.sort(key=lambda x:(-x['score'],x['source_id']))
        engine='bm25-zh-bigram-v1'
        embedding_note='未启用本地语义模型，使用 BM25 关键词检索'
        from backend.embeddings import configured_embeddings, semantic_ranks, EmbeddingUnavailable
        provider=self.embedding_provider
        if provider is None and self.use_configured_embeddings:
            provider,embedding_note=configured_embeddings()
        if provider is not None:
            try:
                order,semantic_scores=semantic_ranks(provider,query,rows)
                semantic_positions={key:index+1 for index,key in enumerate(order)}
                lexical_positions={item['source_id'][3:]:index+1 for index,item in enumerate(results)}
                by_id={item['source_id'][3:]:item for item in results}
                for r in rows:
                    if r[0] not in semantic_positions or r[0] in by_id: continue
                    metadata=json.loads(r[11])
                    by_id[r[0]]=dict(source_id='kb:'+r[0],document_id=r[1],version=r[2],page=r[3],offset=r[4],text=r[5],title=r[7],url=r[8],source_type=r[9],filename=r[10],location_type=metadata.get('location_type','page'),evidence_role=metadata.get('evidence_role','source_material'),**evidence_metadata(metadata,r[1],r[2]),verification='语义相关片段，来源真实性仍需核查')
                for key,item in by_id.items():
                    item['lexical_rank']=lexical_positions.get(key)
                    item['semantic_rank']=semantic_positions.get(key)
                    item['semantic_score']=round(semantic_scores.get(key,0),6)
                    item['score']=round(sum(1/(60+rank) for rank in (lexical_positions.get(key),semantic_positions.get(key)) if rank is not None),8)
                results=sorted(by_id.values(),key=lambda x:(-x['score'],x['source_id']))
                engine='hybrid-bm25-local-rrf-v1'
                embedding_note='本地真实语义向量与 BM25 融合；相关度不是事实置信度'
            except EmbeddingUnavailable as error:
                embedding_note=str(error)
        if style_only:
            # Multiple chunks of one popular post must not crowd out other references.
            unique=[];seen=set()
            for item in results:
                if item['document_id'] not in seen:unique.append(item);seen.add(item['document_id'])
            results=unique
        selected=results[:limit]
        # Keep input costs bounded while preserving exact substrings and locations.
        for source in selected:
            terms=[t for t in wanted if t in source['text'].lower()]
            first=min((source['text'].lower().find(t) for t in terms),default=0)
            start=max(0,first-100)
            source['text']=source['text'][start:start+400]
            source['offset']+=start
        with self.store.connect() as db:
            db.execute('INSERT INTO retrieval_events VALUES(?,?,?,?,?,?)',(str(uuid4()),owner,account,query,json.dumps([r['source_id'] for r in selected]),int(time.time())))
        return {'engine':engine,'embedding_note':embedding_note,'query':query,'sources':selected,'insufficient':not selected,'note':'相关度用于排序，不是事实置信度；仅检索当前账号有效资料'}

    def backfill_classifications(self, owner, account):
        """Append labelled versions; never mutate immutable historical metadata."""
        from backend.creation_taxonomy import classify_document
        self.account(owner,account)
        changed=[]
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute("SELECT d.id,d.title,d.version,v.fingerprint,v.original_base64,v.filename,v.metadata FROM knowledge_documents d JOIN knowledge_versions v ON v.document_id=d.id AND v.version=d.version WHERE d.owner=? AND d.account_id=? AND d.status='active'",(owner,account)).fetchall()
            for identity,title,version,fingerprint,raw,name,packed in rows:
                meta=json.loads(packed)
                if meta.get('classification'):continue
                parts=db.execute('SELECT page,offset_start,text,terms FROM knowledge_chunks WHERE document_id=? AND version=? ORDER BY page,offset_start',(identity,version)).fetchall()
                meta['classification']=classify_document(None,title,' '.join(p[2] for p in parts),meta)
                meta['classification_backfill']={'previous_version':version,'at':int(time.time()),'method':'keyword_inference_v1'}
                db.execute('INSERT INTO knowledge_versions VALUES(?,?,?,?,?,?)',(identity,version+1,fingerprint,raw,name,json.dumps(meta,ensure_ascii=False)))
                for part in parts:db.execute('INSERT INTO knowledge_chunks VALUES(?,?,?,?,?,?,?)',(str(uuid4()),identity,version+1,*part))
                db.execute('UPDATE knowledge_documents SET version=?,updated_at=? WHERE id=?',(version+1,int(time.time()),identity))
                changed.append(identity)
        return {'updated':len(changed),'document_ids':changed}

    def grouped_retrieve(self, owner, account, query, classification, document_ids=None, include_facts=True, include_references=True):
        """Filter before ranking; use explicit BM25 when real vectors are unavailable.

        A successful vector search with no matches stays empty. Neither ranking
        path widens the authorized scope or borrows another domain's examples.
        """
        from backend.creation_taxonomy import classify_task, taxonomy
        from backend.embeddings import configured_embeddings, semantic_ranks, EmbeddingUnavailable
        self.account(owner,account)
        query=validate_text(query,'检索内容',1000)
        original_origin=classification.get('origin')
        classification=classify_task(classification,{'topic':query})
        if original_origin in ('user','inferred'):classification['origin']=original_origin
        if document_ids is not None:
            require(isinstance(document_ids,list) and len(document_ids)<=3 and all(isinstance(x,str) and x for x in document_ids),'INVALID_INPUT','最多选择3份事实资料')
            document_ids=list(dict.fromkeys(document_ids))
        with self.store.connect() as db:
            rows=db.execute("SELECT c.id,c.document_id,c.version,c.page,c.offset_start,c.text,c.terms,d.title,d.source_url,d.source_type,v.filename,v.metadata FROM knowledge_chunks c JOIN knowledge_documents d ON d.id=c.document_id AND d.version=c.version JOIN knowledge_versions v ON v.document_id=c.document_id AND v.version=c.version WHERE d.owner=? AND d.account_id=? AND d.status='active'",(owner,account)).fetchall()
            if document_ids:
                available={r[1] for r in rows}
                require(set(document_ids)<=available,'RESOURCE_NOT_FOUND','所选资料不属于当前账号或已失效')
            rows=[r for r in rows if document_is_public(db,owner,account,json.loads(r[11]),r[8])]
        domains=set(classification['domains']);channel=classification['channel'];form=classification['format']
        groups={k:[] for k in ('methods','examples','facts')};filters={};gaps=[];engines=set()
        cfg=taxonomy()['retrieval'];remaining=cfg['total_chars']
        provider=self.embedding_provider;note=''
        if provider is None and self.use_configured_embeddings:provider,note=configured_embeddings()
        if provider is None:gaps.append({'code':'VECTOR_UNAVAILABLE','detail':note or '未配置真实向量模型；限定范围内使用 BM25 关键词检索','fallback':'bm25'})
        all_meta={r[0]:json.loads(r[11]) for r in rows}
        query_terms=set(tokens(query))
        # Product IDs must match exactly; avoids lending another SKU's specs.
        product_ids=set(re.findall(r'(?<![A-Za-z0-9_-])(?=[A-Za-z0-9_-]*\d)[A-Za-z][A-Za-z0-9_-]{1,}(?![A-Za-z0-9_-])',query))
        for group,kind in (('methods','method'),('examples','example'),('facts','fact')):
            enabled=include_facts if group=='facts' else include_references
            filters[group]={'owner':owner,'account_id':account,'material_type':kind,'domains':sorted(domains),
                            'channel':None if group=='facts' else channel,'format':None if group=='facts' else form,
                            'allow_general':group=='methods','document_ids':document_ids if group=='facts' else None,'enabled':bool(enabled)}
            candidates=[]
            for row in rows:
                meta=all_meta[row[0]];label=meta.get('classification',{})
                if not enabled or not meta.get('retrieval_eligible',True) or label.get('material_type')!=kind:continue
                case=meta.get('research_case',{})
                if case.get('review_required') or case.get('content_kind')=='lead':continue
                if case.get('provenance',{}).get('visibility') in ('private','friends_only'):continue
                if group=='facts' and (meta.get('evidence_role') in ('expression_reference','reference_only') or case.get('evidence_role') in ('expression_reference','reference_only')):continue
                tags=set(label.get('domains',[]))
                if not (tags & domains or (group=='methods' and (not tags or 'general' in tags))):continue
                if group!='facts':
                    if label.get('channel')!=channel and not (group=='methods' and label.get('channel')=='any'):continue
                    if label.get('format')!=form and not (group=='methods' and label.get('format')=='any'):continue
                if group=='facts' and document_ids is not None and row[1] not in document_ids:continue
                if group=='facts':
                    terms=set(tokens(row[7]+' '+row[5]));matched=query_terms & terms
                    if product_ids and not all(re.search(r'(?<![A-Za-z0-9_-])'+re.escape(p)+r'(?![A-Za-z0-9_-])',row[7]+' '+row[5],re.I) for p in product_ids):continue
                    if not matched or (len(query_terms)>3 and len(matched)<2) or len(matched)/max(1,len(query_terms))<0.10:continue
                candidates.append(row)
            filters[group]['candidate_count']=len(candidates)
            search_query=query if group=='facts' else (taxonomy()['formats'][form]['label']+' 原创写作 开篇 节奏 结构 表达 行动引导' if group=='methods' else ' '.join(taxonomy()['domains'][d]['label'] for d in domains)+' '+taxonomy()['formats'][form]['label']+' 开篇 结构 表达')
            filters[group]['vector_query']=search_query
            ranked=[];scores={};admitted=set()
            ranking='vector' if provider is not None else 'bm25'
            if provider is not None and enabled:
                try:
                    # Batch the already-filtered scope, then rank globally.
                    scores={};order=[]
                    for start in range(0,len(candidates),provider.max_chunks):
                        batch_order,batch_scores=semantic_ranks(provider,search_query,candidates[start:start+provider.max_chunks])
                        order.extend(batch_order);scores.update(batch_scores)
                    admitted=set(order)
                except EmbeddingUnavailable as error:
                    # Discard any earlier batch's vectors; never mislabel a partial
                    # vector result as a complete lexical or hybrid search.
                    ranking='bm25'
                    gaps.append({'code':'VECTOR_UNAVAILABLE','group':group,'detail':str(error),'fallback':'bm25'})
            if enabled:
                if ranking=='bm25':
                    scores=bm25_scores(search_query,candidates);admitted=set(scores)
                if candidates:engines.add(ranking)
                for row in candidates:
                    if row[0] not in admitted:continue
                    terms=set(tokens(row[7]+' '+row[5]));coverage=len(query_terms & terms)/max(1,len(query_terms))
                    # BM25 scores are lexical, not normalized semantic similarity.
                    rerank_terms=query_terms if group=='facts' else set(tokens(search_query))
                    rerank_coverage=len(rerank_terms & terms)/max(1,len(rerank_terms))
                    similarity=scores[row[0]] if ranking=='vector' else None
                    rank_score=.8*similarity+.2*rerank_coverage if similarity is not None else scores[row[0]]
                    ranked.append((rank_score,row,similarity,coverage))
                ranked.sort(key=lambda item:(-item[0],item[1][0]))
            filters[group]['retrieval_mode']=ranking if enabled else 'disabled'
            filters[group]['vector_candidate_count']=len(ranked) if ranking=='vector' else 0
            filters[group]['lexical_candidate_count']=len(ranked) if ranking=='bm25' else 0
            seen=set()
            for score,row,similarity,coverage in ranked:
                if len(groups[group])>=cfg['limits'][group] or remaining<=0:break
                if row[1] in seen:continue
                seen.add(row[1]);meta=all_meta[row[0]]
                text=row[5][:min(cfg['chunk_chars'],remaining)];remaining-=len(text)
                groups[group].append(dict(source_id='kb:'+row[0],document_id=row[1],version=row[2],page=row[3],offset=row[4],text=text,title=row[7],url=row[8],source_type=row[9],filename=row[10],location_type=meta.get('location_type','page'),evidence_role='source_material' if group=='facts' else 'expression_reference' if group=='examples' else 'creation_method',**evidence_metadata(meta,row[1],row[2]),score=round(score,6),semantic_score=round(similarity,6) if similarity is not None else None,retrieval_mode=ranking,topic_coverage=round(coverage,6),material_type=kind,verification='原文切片；事实须核验来源，样例仅供表达参考'))
            if enabled and not groups[group]:gaps.append({'code':'NO_MATCHING_'+group.upper(),'group':group,'detail':'限定范围内无匹配材料，不使用无关资料补齐'})
        selected=[s for group in groups.values() for s in group]
        with self.store.connect() as db:db.execute('INSERT INTO retrieval_events VALUES(?,?,?,?,?,?)',(str(uuid4()),owner,account,query,json.dumps([s['source_id'] for s in selected]),int(time.time())))
        engines=engines or ({'vector'} if provider else {'bm25'})
        engine=('filtered-local-vector-bm25-fallback-v1' if len(engines)>1 else
                'filtered-bm25-zh-bigram-v1' if engines=={'bm25'} else 'filtered-local-vector-rerank-v1')
        reranker='cosine-topic-coverage-v1' if engines=={'vector'} else 'per-group-vector-or-bm25' if len(engines)>1 else 'bm25-zh-bigram-v1'
        if 'bm25' in engines:note=(note+'；' if note else '')+'缺失或不可用向量组已降级为限定范围 BM25；不是语义向量结果'
        return {'engine':engine,'reranker':reranker,'classification':classification,'groups':groups,'sources':selected,'filters':filters,'gaps':gaps,'insufficient':not groups['facts'],'context_chars':cfg['total_chars']-remaining,'limits':cfg,'embedding_note':note}

    def classify(self, owner, account, document_id, expected_version, classification):
        """Relabel an owned version without editing source text or case provenance."""
        from backend.creation_taxonomy import classify_document
        self.account(owner,account)
        require(type(expected_version) is int and expected_version>0,'INVALID_INPUT','资料版本无效')
        # Validate independently before opening a write transaction.
        require(isinstance(classification,dict),'INVALID_INPUT','请选择资料分类')
        label=classify_document(classification,'','')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT d.version,d.source_url,v.fingerprint,v.original_base64,v.filename,v.metadata FROM knowledge_documents d JOIN knowledge_versions v ON v.document_id=d.id AND v.version=d.version WHERE d.id=? AND d.owner=? AND d.account_id=? AND d.status='active'",(document_id,owner,account)).fetchone()
            require(row is not None,'RESOURCE_NOT_FOUND','资料不可访问')
            require(row[0]==expected_version,'VERSION_CONFLICT','资料已更新，请刷新后重新分类')
            meta=json.loads(row[5])
            require(document_is_public(db,owner,account,meta,row[1]),'RESOURCE_NOT_FOUND','资料当前不可访问')
            case=meta.get('research_case',{})
            require(case.get('provenance',{}).get('visibility') not in ('private','friends_only'),'RESOURCE_NOT_FOUND','资料当前不可访问')
            expression_roles={'expression_reference','reference_only'}
            require(not (label['material_type']=='fact' and (meta.get('evidence_role') in expression_roles or case.get('evidence_role') in expression_roles)),
                    'CASE_EDIT_REQUIRED','表达参考不能仅通过分类改成事实；请在案例编辑中核对并修改证据用途')
            previous=meta.get('classification')
            meta['classification']=label
            meta['classification_change']={'previous_version':row[0],'previous_classification':previous,'at':int(time.time()),'method':'user_classification_only'}
            version=row[0]+1
            db.execute('INSERT INTO knowledge_versions VALUES(?,?,?,?,?,?)',(document_id,version,row[2],row[3],row[4],json.dumps(meta,ensure_ascii=False)))
            parts=db.execute('SELECT page,offset_start,text,terms FROM knowledge_chunks WHERE document_id=? AND version=? ORDER BY page,offset_start',(document_id,row[0])).fetchall()
            for part in parts:db.execute('INSERT INTO knowledge_chunks VALUES(?,?,?,?,?,?,?)',(str(uuid4()),document_id,version,*part))
            db.execute('UPDATE knowledge_documents SET version=?,updated_at=? WHERE id=?',(version,int(time.time()),document_id))
        return self.get(owner,account,document_id)

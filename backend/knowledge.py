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
        text=text.replace('\x00','').replace('\r\n','\n').strip()
        for start in range(0,len(text),650):
            excerpt=text[start:start+800]
            if excerpt.strip(): result.append({'page':page,'offset':start,'text':excerpt})
    return result


def evidence_metadata(metadata, document_id, version):
    case=metadata.get('research_case',{})
    return {'content_kind':case.get('content_kind','text'),
            'source_scope':'current_account',
            'case_ref':({'document_id':document_id,'version':version,'platform':case.get('platform'),
                         'published_at':case.get('published_at'),'observed_at':case.get('observed_at'),
                         'assessment_status':case.get('assessment',{}).get('status'),
                         'verification':case.get('verification')} if case else None)}


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

    def save(self, owner, data, source_type='text', source_url='', metadata=None, *, transaction_guard=None, transaction_saved=None):
        require(isinstance(data,dict) and set(data)<={'account_id','title','text','filename','file_base64','document_id','expected_version'},'INVALID_INPUT','资料字段无效')
        account=data.get('account_id');self.account(owner,account)
        title=validate_text(data.get('title'),'资料标题',200)
        name=data.get('filename',title+'.txt')
        if 'file_base64' in data:
            require(isinstance(data['file_base64'],str) and len(data['file_base64'])<=4_000_000,'INVALID_INPUT','文件超过 3 MB')
            try: raw=base64.b64decode(data['file_base64'],validate=True)
            except (ValueError,TypeError): raise ValueError('文件编码无效') from None
            pages=parse_file(name,raw); source_type='upload'
        else:
            text=validate_text(data.get('text'),'资料正文',MAX_TEXT)
            raw=text.encode();pages=[(1,text)]
        parts=chunks(pages)
        fingerprint=hashlib.sha256(raw).hexdigest();now=int(time.time())
        identity=data.get('document_id') or str(uuid4())
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if transaction_guard is not None: transaction_guard(db)
            row=db.execute('SELECT version,status FROM knowledge_documents WHERE id=? AND owner=? AND account_id=?',(identity,owner,account)).fetchone()
            if data.get('document_id'):
                require(row and row[1]=='active','RESOURCE_NOT_FOUND','资料不可访问')
                require(type(data.get('expected_version')) is int and data['expected_version']==row[0],'VERSION_CONFLICT','资料已更新，请刷新')
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
            db.execute('INSERT INTO knowledge_versions VALUES(?,?,?,?,?,?)',(identity,version,fingerprint,base64.b64encode(raw).decode(),name,json.dumps(meta,ensure_ascii=False)))
            for part in parts:
                db.execute('INSERT INTO knowledge_chunks VALUES(?,?,?,?,?,?,?)',(str(uuid4()),identity,version,part['page'],part['offset'],part['text'],json.dumps(Counter(tokens(part['text'])),ensure_ascii=False)))
            if transaction_saved is not None: transaction_saved(db,identity,version)
        return self.get(owner,account,identity)

    def list(self, owner, account):
        self.account(owner,account)
        with self.store.connect() as db:
            rows=db.execute("SELECT d.id,d.title,d.version,d.source_type,d.source_url,d.updated_at,v.filename,v.metadata FROM knowledge_documents d JOIN knowledge_versions v ON v.document_id=d.id AND v.version=d.version WHERE d.owner=? AND d.account_id=? AND d.status='active' ORDER BY d.updated_at DESC,d.id",(owner,account)).fetchall()
        return [dict(zip(('id','title','version','source_type','source_url','updated_at','filename'),r[:7]),metadata=json.loads(r[7])) for r in rows]

    def get(self, owner, account, identity):
        self.account(owner,account)
        with self.store.connect() as db:
            row=db.execute("SELECT title,version,source_type,source_url FROM knowledge_documents WHERE owner=? AND account_id=? AND id=? AND status='active'",(owner,account,identity)).fetchone()
            require(row,'RESOURCE_NOT_FOUND','资料不可访问')
            v=db.execute('SELECT fingerprint,metadata,filename FROM knowledge_versions WHERE document_id=? AND version=?',(identity,row[1])).fetchone()
            parts=db.execute('SELECT id,page,offset_start,text FROM knowledge_chunks WHERE document_id=? AND version=? ORDER BY page,offset_start',(identity,row[1])).fetchall()
            versions=[dict(version=r[0],metadata=json.loads(r[1])) for r in db.execute('SELECT version,metadata FROM knowledge_versions WHERE document_id=? ORDER BY version DESC',(identity,))]
        return dict(id=identity,title=row[0],version=row[1],source_type=row[2],source_url=row[3],fingerprint=v[0],metadata=json.loads(v[1]),filename=v[2],versions=versions,chunks=[dict(zip(('id','page','offset','text'),p)) for p in parts])

    def delete(self, owner, account, identity, version):
        self.account(owner,account)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT version FROM knowledge_documents WHERE id=? AND owner=? AND account_id=? AND status='active'",(identity,owner,account)).fetchone()
            require(row,'RESOURCE_NOT_FOUND','资料不可访问')
            require(type(version) is int and row[0]==version,'VERSION_CONFLICT','资料版本已变化')
            db.execute("UPDATE knowledge_documents SET status='deleted' WHERE id=?",(identity,))
        return {'deleted':True,'note':'后续检索已排除；已有任务的证据快照保留审计'}

    def retrieve(self, owner, account, query, limit=4, document_ids=None):
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
        documents=[(r,json.loads(r[6])) for r in rows]
        n=len(documents);avg=sum(sum(t.values()) for _,t in documents)/max(1,n)
        df={t:sum(t in terms for _,terms in documents) for t in wanted}
        results=[]
        for r,terms in documents:
            matched=wanted & terms.keys()
            if not matched: continue
            length=sum(terms.values())
            score=sum(math.log(1+(n-df[t]+0.5)/(df[t]+0.5))*(terms[t]*2.2)/(terms[t]+1.2*(.25+.75*length/max(1,avg))) for t in matched)
            # A lone accidental bigram in a long question is insufficient evidence.
            if len(wanted)>3 and len(matched)<2: continue
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

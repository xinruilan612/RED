"""Account-scoped, versioned evidence and deterministic lexical RAG.

No fake embeddings: initial retrieval is BM25 over Chinese character bigrams
and Latin words. Original files, page locations and immutable excerpts persist.
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
    else:
        raise ValueError('目前支持 UTF-8 TXT、Markdown 和文本型 PDF')
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


class Knowledge:
    def __init__(self, store):
        self.store=store
        with store.connect() as db:
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

    def save(self, owner, data, source_type='text', source_url='', metadata=None):
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
            raw=text.encode('utf-8');pages=[(1,text)]
        fingerprint=hashlib.sha256(raw).hexdigest();now=int(time.time())
        identity=data.get('document_id') or str(uuid4())
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
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
            self._write_version(db, owner, account, identity, version, title, raw, pages,
                                name, source_type, source_url, metadata, now)
        return self.get(owner,account,identity)

    def _write_version(self, db, owner, account, identity, version, title, raw, pages,
                       filename, source_type, source_url, metadata, stored_at):
        """Write under the caller's validated transaction; never commits separately."""
        if version > 1:
            db.execute('UPDATE knowledge_documents SET title=?,version=?,source_type=?,source_url=?,updated_at=? WHERE id=?',
                       (title,version,source_type,source_url,stored_at,identity))
        else:
            db.execute('INSERT INTO knowledge_documents VALUES(?,?,?,?,?,?,?,?,?)',
                       (identity,owner,account,title,version,'active',source_type,source_url,stored_at))
        meta={**(metadata or {}),'title':title,'source_type':source_type,'source_url':source_url,
              'stored_at':stored_at,'page_count':len(pages)}
        db.execute('INSERT INTO knowledge_versions VALUES(?,?,?,?,?,?)',
                   (identity,version,hashlib.sha256(raw).hexdigest(),base64.b64encode(raw).decode('ascii'),
                    filename,json.dumps(meta,ensure_ascii=False)))
        for part in chunks(pages):
            db.execute('INSERT INTO knowledge_chunks VALUES(?,?,?,?,?,?,?)',
                       (str(uuid4()),identity,version,part['page'],part['offset'],part['text'],
                        json.dumps(Counter(tokens(part['text'])),ensure_ascii=False)))

    def list(self, owner, account):
        self.account(owner,account)
        with self.store.connect() as db:
            rows=db.execute("SELECT id,title,version,source_type,source_url,updated_at FROM knowledge_documents WHERE owner=? AND account_id=? AND status='active' ORDER BY updated_at DESC,id",(owner,account)).fetchall()
        return [dict(zip(('id','title','version','source_type','source_url','updated_at'),r)) for r in rows]

    def get(self, owner, account, identity, version=None):
        require(version is None or (type(version) is int and 0 < version <= 2147483647),
                'INVALID_INPUT','资料版本需为正整数')
        self.account(owner,account)
        with self.store.connect() as db:
            row=db.execute("SELECT title,version,source_type,source_url FROM knowledge_documents WHERE owner=? AND account_id=? AND id=? AND status='active'",(owner,account,identity)).fetchone()
            require(row,'RESOURCE_NOT_FOUND','资料不可访问')
            selected=version if version is not None else row[1]
            v=db.execute('SELECT fingerprint,metadata,filename,original_base64 FROM knowledge_versions WHERE document_id=? AND version=?',(identity,selected)).fetchone()
            require(v,'RESOURCE_NOT_FOUND','资料版本不存在')
            parts=db.execute('SELECT id,page,offset_start,text FROM knowledge_chunks WHERE document_id=? AND version=? ORDER BY page,offset_start',(identity,selected)).fetchall()
            versions=[dict(version=r[0],metadata=json.loads(r[1]),fingerprint=r[2],filename=r[3]) for r in db.execute('SELECT version,metadata,fingerprint,filename FROM knowledge_versions WHERE document_id=? ORDER BY version DESC',(identity,))]
        meta=json.loads(v[1])
        # Never attribute today's source/title/date to historical bytes. Older
        # records without a metadata snapshot remain explicitly unknown.
        return dict(id=identity,title=meta.get('title','标题未记录'),version=selected,
                    current_version=row[1],read_only=selected!=row[1],
                    source_type=meta.get('source_type','unknown'),source_url=meta.get('source_url',''),
                    source_recorded='source_type' in meta and 'source_url' in meta,
                    stored_at=meta.get('stored_at'),fingerprint=v[0],metadata=meta,filename=v[2],
                    original_base64=v[3],versions=versions,
                    chunks=[dict(zip(('id','page','offset','text'),p)) for p in parts])

    def delete(self, owner, account, identity, version):
        self.account(owner,account)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT version FROM knowledge_documents WHERE id=? AND owner=? AND account_id=? AND status='active'",(identity,owner,account)).fetchone()
            require(row,'RESOURCE_NOT_FOUND','资料不可访问')
            require(type(version) is int and row[0]==version,'VERSION_CONFLICT','资料版本已变化')
            db.execute("UPDATE knowledge_documents SET status='deleted' WHERE id=?",(identity,))
        return {'deleted':True,'note':'后续检索已排除；已有任务的证据快照保留审计'}

    def retrieve(self, owner, account, query, limit=4):
        self.account(owner,account);query=validate_text(query,'检索内容',300)
        wanted=set(tokens(query))
        with self.store.connect() as db:
            rows=db.execute("SELECT c.id,c.document_id,c.version,c.page,c.offset_start,c.text,c.terms,d.title,d.source_url,d.source_type,v.fingerprint,v.metadata FROM knowledge_chunks c JOIN knowledge_documents d ON d.id=c.document_id AND d.version=c.version JOIN knowledge_versions v ON v.document_id=c.document_id AND v.version=c.version WHERE d.owner=? AND d.account_id=? AND d.status='active'",(owner,account)).fetchall()
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
            provenance=[metadata.get(key) for key in ('source_label','author','verification')]
            verification='；'.join(['原文片段匹配，来源真实性仍需核查']+
                                    [value for value in provenance if isinstance(value,str) and value])
            results.append(dict(source_id='kb:'+r[0],document_id=r[1],version=r[2],page=r[3],offset=r[4],text=r[5],title=r[7],url=r[8],source_type=r[9],fingerprint=r[10],metadata=metadata,score=round(score,4),verification=verification))
        results.sort(key=lambda x:(-x['score'],x['source_id']))
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
        return {'engine':'bm25-zh-bigram-v1','query':query,'sources':selected,'insufficient':not selected,'note':'相关度用于排序，不是事实置信度；仅检索当前账号有效资料'}

"""Explicit, offline conversion of an owned browser observation to a RAG case.

Only the note's text enters Knowledge. Comments never enter this import path.
Unknown metrics remain null; this adapter does not confer official verification.
"""
import hashlib
import json
from datetime import datetime, timezone
from backend.contracts import DomainError, require
from backend.research_cases import ResearchCases, METRICS


class XHSCaseImport:
    def __init__(self,store):
        self.store=store
        self.cases=ResearchCases(store)

    @staticmethod
    def _existing(db,owner,account,url):
        rows=db.execute("SELECT d.id,d.version,v.fingerprint,v.metadata FROM knowledge_documents d JOIN knowledge_versions v ON v.document_id=d.id AND v.version=d.version WHERE d.owner=? AND d.account_id=? AND d.status='active' AND d.source_type='research_case' AND d.source_url=?",(owner,account,url)).fetchall()
        return next((r[:3] for r in rows if json.loads(r[3]).get('research_case',{}).get('source_method')=='local_browser_mcp'),None)

    def save(self,owner,data):
        require(isinstance(data,dict) and set(data)=={'account_id','note_id','permission_confirmed'},'INVALID_INPUT','导入字段无效')
        require(data['permission_confirmed'] is True,'INVALID_INPUT','请确认有权将此笔记用于表达参考')
        account,note_id=data['account_id'],data['note_id']
        self.cases.knowledge.account(owner,account)
        require(isinstance(note_id,str) and 0<len(note_id)<=200,'INVALID_INPUT','笔记标识无效')
        for _ in range(3):
            with self.store.connect() as db:
                row=db.execute("SELECT payload,hash,last_seen FROM xhs_sync_entities WHERE owner=? AND account_id=? AND kind='note' AND id=?",(owner,account,note_id)).fetchone()
                require(row is not None,'RESOURCE_NOT_FOUND','未找到此账号的已保存笔记')
                note=json.loads(row[0])
                require(note.get('id')==note_id and note.get('url')=='https://www.xiaohongshu.com/explore/'+note_id,'INVALID_INPUT','笔记来源标识不一致')
                link=db.execute('SELECT source_id FROM xhs_sync_links WHERE owner=? AND account_id=?',(owner,account)).fetchone()
                require(link and note.get('author_id')==link[0],'FORBIDDEN','笔记不是绑定账号本人内容')
                existing=self._existing(db,owner,account,note['url'])
            body=note['text'].strip()
            require(body,'INVALID_INPUT','笔记没有可导入的文字正文')
            fingerprint=hashlib.sha256(body.encode()).hexdigest()
            if existing and existing[2]==fingerprint:
                return {**self.cases.knowledge.get_version(owner,account,existing[0],existing[1]),'reused':True}
            observed=datetime.fromtimestamp(row[2],timezone.utc).isoformat()
            packet={'account_id':account,'title':(note['title'].strip() or '本人笔记表达参考')[:200],
                    'text':body,'source_url':note['url'],'platform':'xiaohongshu','author':note['author_id'],
                    'observed_at':observed,'metrics':{key:note['metrics'].get(key) for key in METRICS},'content_kind':'text',
                    'evidence_role':'expression_reference','permission_confirmed':True}
            if existing:packet.update(document_id=existing[0],expected_version=existing[1])
            def guard(db):
                current=db.execute("SELECT hash FROM xhs_sync_entities WHERE owner=? AND account_id=? AND kind='note' AND id=?",(owner,account,note_id)).fetchone()
                require(current and current[0]==row[1] and self._existing(db,owner,account,note['url'])==existing,
                        'VERSION_CONFLICT','笔记或案例已更新，请重试')
            try:
                return {**self.cases.save(owner,packet,source_method='local_browser_mcp',fetched_at=observed,transaction_guard=guard),'reused':False}
            except DomainError as exc:
                if exc.code!='VERSION_CONFLICT':raise
        raise DomainError('VERSION_CONFLICT','笔记或案例持续更新，请稍后重试')

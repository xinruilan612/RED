"""Local media previews: only human-reviewed versions enter retrieval."""
import base64
import binascii
import hashlib
import threading
from backend.contracts import require
from backend.local_transcription import MAX_BYTES, transcribe_upload
from backend.research_cases import ResearchCases

_PROCESS_LOCK=threading.Lock()


class MediaCases:
    def __init__(self,store,transcriber=None):
        self.cases=ResearchCases(store);self.transcriber=transcriber or transcribe_upload

    def create(self,owner,data):
        require(isinstance(data,dict) and set(data)=={'account_id','title','filename','file_base64','permission_confirmed'},'INVALID_INPUT','转写字段无效')
        self.cases.knowledge.account(owner,data['account_id'])
        require(data['permission_confirmed'] is True,'INVALID_INPUT','请确认有权使用此媒体')
        require(isinstance(data['file_base64'],str) and len(data['file_base64'])<=(MAX_BYTES+2)//3*4,'INVALID_INPUT','媒体文件不得超过10MB')
        try:raw=base64.b64decode(data['file_base64'],validate=True)
        except (ValueError,binascii.Error):require(False,'INVALID_INPUT','媒体编码无效')
        require(0<len(raw)<=MAX_BYTES,'INVALID_INPUT','媒体文件必须是10MB以内的非空文件')
        fingerprint=hashlib.sha256(raw).hexdigest()
        require(_PROCESS_LOCK.acquire(blocking=False),'TRANSCRIPTION_BUSY','本机正在转写其他文件，请稍后重试')
        try:
            for doc in self.cases.list(owner,data['account_id']):
                case=doc['metadata'].get('research_case',{})
                if case.get('provenance',{}).get('source_sha256')==fingerprint:
                    return self.cases.knowledge.get(owner,data['account_id'],doc['id'])
            result=self.transcriber(raw,filename=data['filename'],account_id=data['account_id'],title=data['title'],permission_confirmed=True,platform='owned')
            return self.cases.save(owner,result['payload'],source_method='local_whisper_audio_only',
                provenance=result['provenance'],review_required=True)
        finally:_PROCESS_LOCK.release()

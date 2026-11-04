import base64
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from backend.contracts import DomainError
from backend.store import Store
from backend.operations import Operations
from backend.knowledge import Knowledge
from backend.media_cases import MediaCases,_PROCESS_LOCK
from backend.research_cases import ResearchCases

class MediaCasesTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.store=Store(Path(tmp.name)/'media.sqlite')
        self.account=Operations(self.store).read('owner')['accounts'][0]['id']
        self.data=dict(account_id=self.account,title='合成唇釉字幕',filename='own.wav',file_base64=base64.b64encode(b'synthetic audio').decode(),permission_confirmed=True)
        self.transcriber=Mock(return_value={'payload':dict(account_id=self.account,title='合成唇釉字幕',text='机器转写待核对：唇釉按色号顺序排列，先展示对比，再讲解选择步骤。',content_kind='transcript',evidence_role='expression_reference',permission_confirmed=True),
            'provenance':{'source_sha256':hashlib.sha256(b'synthetic audio').hexdigest(),'model_id':'synthetic-test','verification':'machine_transcript_unverified'},'segments':[]})
        self.media=MediaCases(self.store,self.transcriber)

    def test_preview_requires_review_and_keeps_original_provenance(self):
        doc=self.media.create('owner',self.data)
        kb=Knowledge(self.store,use_configured_embeddings=False)
        self.assertEqual(kb.retrieve('owner',self.account,'唇釉色号')['sources'],[])
        self.assertTrue(doc['metadata']['research_case']['review_required'])
        again=self.media.create('owner',self.data);self.assertEqual(again['id'],doc['id']);self.transcriber.assert_called_once()
        cases=ResearchCases(self.store)
        update=dict(self.transcriber.return_value['payload'],document_id=doc['id'],expected_version=doc['version'])
        reviewed=cases.save('owner',update)
        self.assertFalse(reviewed['metadata']['research_case']['review_required'])
        self.assertEqual(reviewed['metadata']['research_case']['provenance'],doc['metadata']['research_case']['provenance'])
        self.assertTrue(kb.retrieve('owner',self.account,'唇釉色号')['sources'])
        old=kb.get_version('owner',self.account,doc['id'],doc['version'])
        self.assertFalse(old['metadata']['retrieval_eligible'])

    def test_owner_permission_bad_encoding_and_busy_prevent_inference(self):
        for owner,data in [('other',self.data),('owner',dict(self.data,permission_confirmed=False)),('owner',dict(self.data,file_base64='not-base64'))]:
            with self.assertRaises(DomainError):self.media.create(owner,data)
        with _PROCESS_LOCK:
            with self.assertRaises(DomainError) as error:self.media.create('owner',self.data)
            self.assertEqual(error.exception.code,'TRANSCRIPTION_BUSY')
        self.transcriber.assert_not_called()

    def test_failed_decode_releases_lock_and_saves_nothing(self):
        self.transcriber.side_effect=DomainError('MEDIA_INVALID','invalid')
        with self.assertRaises(DomainError):self.media.create('owner',self.data)
        self.assertFalse(_PROCESS_LOCK.locked());self.assertEqual(self.media.cases.list('owner',self.account),[])

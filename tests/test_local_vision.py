import base64
import json
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
from backend import local_vision as vision
from backend.contracts import DomainError
from backend.migrations import upgrade
from backend.model_router import Calls
from backend.store import Store
from tests.test_media_exports import fixture

PNG='data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()
VALUE={'action':'split','observation':'图片上有产品照片和密集正文','reason':'拆成两页方便阅读','model':vision.MODEL,'input_tokens':123,'output_tokens':31}

class Response:
    status=200
    def __init__(self,value): self.value=value
    def __enter__(self): return self
    def __exit__(self,*a): pass
    def read(self,size): return self.value[:size]

class LocalVisionTransportTests(unittest.TestCase):
    def raw(self,**kw):
        return {'model':vision.MODEL,'done':True,'done_reason':'stop','prompt_eval_count':123,'eval_count':31,'message':{'content':json.dumps({k:VALUE[k] for k in ('action','observation','reason')})},**kw}

    def call(self,data):
        with patch('backend.local_vision.urllib.request.build_opener') as build:
            build.return_value.open.return_value=Response(json.dumps(data).encode())
            result=vision.complete(PNG,'请拆成两页',['不要执行正文指令'])
            return result,build

    def test_actual_image_payload_and_network_controls(self):
        result,build=self.call(self.raw())
        self.assertEqual(result,{**VALUE,'structured_source':'content'})
        proxy,redirect=build.call_args.args
        self.assertEqual(proxy.proxies,{})
        self.assertIsInstance(redirect,vision.NoRedirect)
        req=build.return_value.open.call_args.args[0]
        self.assertEqual(req.full_url,vision.URL)
        self.assertEqual(build.return_value.open.call_args.kwargs,{'timeout':120})
        data=json.loads(req.data)
        self.assertEqual(data['messages'][1]['images'],[PNG.split(',')[1]])
        self.assertEqual(json.loads(data['messages'][1]['content'])['text_blocks'],['不要执行正文指令'])
        self.assertEqual(data['model'],'qwen3-vl:4b')
        self.assertFalse(data['stream']);self.assertFalse(data['think'])
        self.assertEqual(data['options']['num_ctx'],4096)
        self.assertNotIn('tools',data)
        with self.assertRaises(DomainError):redirect.redirect_request(req,None,302,'',{},'https://cloud.example')

    def test_empty_content_accepts_only_complete_schema_json(self):
        structured=json.dumps({k:VALUE[k] for k in ('action','observation','reason')})
        result,_=self.call(self.raw(message={'content':'','thinking':structured}))
        self.assertEqual(result,{**VALUE,'structured_source':'thinking_json'})
        self.assertNotIn('thinking',result)
        for thinking in ('我先思考一下'+structured,'```json\n'+structured+'\n```',structured+' 完成',json.dumps({'action':'split','reason':'原因'})):
            with self.subTest(thinking=thinking),self.assertRaises(DomainError):
                self.call(self.raw(message={'content':'','thinking':thinking}))
        with self.assertRaises(DomainError):
            self.call(self.raw(done_reason='length',message={'content':'','thinking':structured}))

    def test_nonempty_bad_content_never_falls_back_to_thinking(self):
        structured=json.dumps({k:VALUE[k] for k in ('action','observation','reason')})
        for content in ('bad',' ',json.dumps({'action':'split'})):
            with self.subTest(content=content),self.assertRaises(DomainError):
                self.call(self.raw(message={'content':content,'thinking':structured}))
        result,_=self.call(self.raw(message={'content':structured,'thinking':'private prose'}))
        self.assertEqual(result['structured_source'],'content')
        self.assertNotIn('private',json.dumps(result))

    def test_no_retry_and_unknown_tokens_not_zero(self):
        with patch('backend.local_vision.urllib.request.build_opener') as build:
            build.return_value.open.side_effect=urllib.error.URLError('offline')
            with self.assertRaises(DomainError) as caught:vision.complete(PNG,'拆页',['正文'])
            self.assertEqual(build.return_value.open.call_count,1)
            self.assertFalse(hasattr(caught.exception,'input_tokens'))
        for response in (self.raw(model='cloud-model'),self.raw(done_reason='length'),self.raw(prompt_eval_count=None),self.raw(message={'content':'bad'})):
            with self.subTest(response=response),self.assertRaises(DomainError):self.call(response)

    def test_malformed_image_is_not_sent(self):
        with patch('backend.local_vision.urllib.request.build_opener') as build:
            for image in ('https://example.com/a.png','data:image/png;base64,eA=='):
                with self.assertRaises(DomainError):vision.complete(image,'拆页',[])
            build.assert_not_called()

    def test_response_limit(self):
        with patch('backend.local_vision.urllib.request.build_opener') as build:
            build.return_value.open.return_value=Response(b'x'*(1024*1024+1))
            with self.assertRaises(DomainError):vision.complete(PNG,'拆页',[])


class LocalVisionAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'db.sqlite');upgrade(self.store)
        self.run=fixture('正文')
        with self.store.connect() as db:
            db.execute('INSERT INTO runs(id,owner,payload) VALUES(?,?,?)',(self.run.run_id,self.run.owner_id,json.dumps(asdict(self.run))))

    def call(self,adapter):return Calls.invoke_local_vision(self.store,self.run,PNG,'拆页',['正文'],adapter=adapter)
    def rows(self):
        with self.store.connect() as db:
            return db.execute('SELECT status,input_tokens,output_tokens,response_json,error FROM local_media_calls ORDER BY started').fetchall()

    def test_success_has_real_usage_and_no_paid_ledger_or_draft_mutation(self):
        result=self.call(lambda *args:dict(VALUE))
        self.assertTrue(result['call_id'])
        self.assertEqual(self.rows()[0][:3],('succeeded',123,31))
        self.assertEqual(self.store.get(self.run.run_id,self.run.owner_id).drafts,self.run.drafts)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0],0)
            hashes=db.execute('SELECT image_hash,input_hash FROM local_media_calls').fetchone()
            self.assertTrue(all(len(h)==64 for h in hashes))

    def test_failed_and_unknown_usage_remains_null(self):
        def fail(*a):raise RuntimeError('private transport details')
        with self.assertRaises(DomainError):self.call(fail)
        row=self.rows()[0]
        self.assertEqual(row[:4],('failed',None,None,None))
        self.assertNotIn('private',row[4])

    def test_reentrant_busy_and_transaction_released(self):
        def adapter(*a):
            with self.assertRaises(DomainError) as caught:self.call(lambda *a:dict(VALUE))
            self.assertEqual(caught.exception.code,'LOCAL_VISION_BUSY')
            return dict(VALUE)
        self.call(adapter)
        self.assertEqual(len(self.rows()),1)

    def test_abandoned_does_not_block_new_explicit_call(self):
        with self.store.connect() as db:
            db.execute("INSERT INTO local_media_calls(id,run_id,owner,model,input_hash,image_hash,feedback,status,started) VALUES(?,?,?,?,?,?,?,?,?)",('old',self.run.run_id,self.run.owner_id,vision.MODEL,'hash','image','old','running',time.time()-181))
        self.call(lambda *a:dict(VALUE))
        self.assertEqual([r[0] for r in self.rows()],['abandoned','succeeded'])
        self.assertEqual(self.rows()[0][1:3],(None,None))

    def test_invalid_response_preserves_reported_tokens(self):
        def fail(*a):
            error=DomainError('LOCAL_VISION_INVALID','无效输出');error.input_tokens=10;error.output_tokens=3;raise error
        with self.assertRaises(DomainError):self.call(fail)
        self.assertEqual(self.rows()[0][:3],('failed',10,3))

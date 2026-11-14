"""Product-image boundaries, isolated accounting, idempotence and HTTP access."""
import base64
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4
from PIL import Image
from cryptography.fernet import Fernet
from backend.contracts import DomainError
from backend.credentials import CredentialVault
from backend.product_images import ProductImages, image_input
from backend.provider import Config
from backend.service import Service
from backend.store import Store


def png():
    stream=io.BytesIO();Image.new('RGB',(80,60),'white').save(stream,format='PNG')
    return base64.b64encode(stream.getvalue()).decode()


class ProductImageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'test.sqlite');self.prepare()

    def prepare(self):
        self.service=Service(self.store,Config())
        self.service.models.vault=CredentialVault(self.store,environ={'MODEL_CREDENTIAL_KEY':Fernet.generate_key().decode()})
        self.images=ProductImages(self.service)
        self.account=self.service.operations.read('alice')['accounts'][0]['id']
        self.ocr=patch('backend.product_images.local_ocr',return_value=['测试牌保湿乳','净含量 50 mL'])
        self.ocr_mock=self.ocr.start();self.addCleanup(self.ocr.stop)

    def payload(self,**extra):
        return dict(account_id=self.account,request_id=str(uuid4()),filename='产品.png',file_base64=png(),mode='local',**extra)

    def vision(self):
        connection=self.service.models.save('alice',dict(provider='qwen',model='vision-test-fixture',api_key='fake-offline-key',rate_usd_per_million=2,run_budget_usd=1,day_budget_usd=5))
        data=self.payload();data.update(mode='vision',connection_id=connection['id'],acknowledge_cost=True)
        return data

    def adapter(self):
        return Mock(connection={'protocol':'openai'},complete_result=Mock(return_value=(dict(product_name='测试牌保湿乳',brand='测试牌',model='',category='乳液',visible_text=['50 mL'],appearance='白色瓶子',uncertainties=['型号不可见']),200,{})))

    def test_preview_is_not_rag_and_original_is_preserved(self):
        data=self.payload();result=self.images.preview('alice',data)
        self.assertFalse(result['confirmed']);self.assertIn('50 mL',result['text'])
        self.assertEqual(self.service.knowledge.list('alice',self.account),[])
        self.assertEqual(self.images.original('alice',result['id']),base64.b64decode(data['file_base64']))

    def test_confirm_edited_text_once_and_retrieve(self):
        result=self.images.preview('alice',self.payload())
        data=dict(account_id=self.account,title='已核对保湿乳',text='测试牌保湿乳净含量50 mL。包装文字经本人核对；其他内容未知。',confirmed=True)
        saved=self.images.confirm('alice',result['id'],data)
        repeated=self.images.confirm('alice',result['id'],data)
        self.assertEqual(saved['id'],repeated['id'])
        self.assertEqual(len(self.service.knowledge.list('alice',self.account)),1)
        self.assertTrue(saved['metadata']['product_image']['confirmed'])
        self.assertIn('50 mL',self.service.knowledge.get('alice',self.account,saved['id'])['chunks'][0]['text'])

    def test_no_cross_owner_read_or_confirm(self):
        result=self.images.preview('alice',self.payload())
        for operation in (lambda:self.images.original('bob',result['id']),lambda:self.images.confirm('bob',result['id'],dict(account_id=self.account,title='x',text='x',confirmed=True))):
            with self.assertRaises(DomainError):operation()
        with self.assertRaises(DomainError):self.images.preview('bob',self.payload())

    def test_request_replay_does_not_repeat_ocr(self):
        data=self.payload();first=self.images.preview('alice',data)
        self.assertEqual(self.images.preview('alice',data),first)
        self.assertEqual(self.ocr_mock.call_count,1)
        data['filename']='changed.jpg';data['file_base64']=base64.b64encode(b'not an image').decode()
        with self.assertRaises(DomainError):self.images.preview('alice',data)

    def test_bad_raster_and_oversized_input_rejected(self):
        for changes in ({'filename':'bad.svg'},{'file_base64':'notbase64'},{'file_base64':'A'*4_000_004},{'file_base64':base64.b64encode(b'not-an-image').decode()}):
            data=self.payload();data.update(changes)
            with self.assertRaises(DomainError):self.images.preview('alice',data)

    def test_high_pixel_count_and_animated_image_rejected(self):
        stream=io.BytesIO();Image.new('RGB',(4001,3000),'white').save(stream,format='PNG')
        data=self.payload();data['file_base64']=base64.b64encode(stream.getvalue()).decode()
        with self.assertRaisesRegex(DomainError,'像素'):self.images.preview('alice',data)

    def test_supported_formats_are_decoded_and_metadata_is_not_transmitted(self):
        for fmt,suffix in (('JPEG','jpg'),('PNG','png'),('WEBP','webp')):
            stream=io.BytesIO();Image.new('RGB',(50,40),'white').save(stream,format=fmt)
            raw,clean=image_input({'filename':'p.'+suffix,'file_base64':base64.b64encode(stream.getvalue()).decode()})
            self.assertEqual(raw,stream.getvalue())
            with Image.open(io.BytesIO(clean)) as image:
                self.assertEqual(image.format,'JPEG');self.assertFalse(image.getexif())

    def test_no_text_remains_unknown(self):
        self.ocr_mock.return_value=[]
        result=self.images.preview('alice',self.payload())
        self.assertEqual(result['result']['product_name'],'');self.assertIn('未识别到清晰文字',result['text'])

    def test_vision_requires_explicit_connection_and_cost(self):
        data=self.payload();data['mode']='vision'
        with self.assertRaises(DomainError):self.images.preview('alice',data)
        data['acknowledge_cost']=True
        with self.assertRaisesRegex(DomainError,'模型连接'):self.images.preview('alice',data)

    def test_vision_transmits_image_once_and_settles_shared_accounting(self):
        data=self.vision();adapter=self.adapter()
        with patch.object(self.service.models,'adapter',return_value=adapter):
            result=self.images.preview('alice',data)
            self.assertEqual(self.images.preview('alice',data),result)
        self.assertEqual(adapter.complete_result.call_count,1)
        messages=adapter.complete_result.call_args.args[0]
        self.assertTrue(messages[1]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,'))
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT tokens FROM model_connection_tests WHERE id=?',(data['request_id'],)).fetchone()[0],200)

    def test_failure_is_not_automatically_replayed(self):
        data=self.vision();adapter=self.adapter();adapter.complete_result.side_effect=DomainError('PROVIDER_ERROR','timeout')
        with patch.object(self.service.models,'adapter',return_value=adapter):
            with self.assertRaises(DomainError):self.images.preview('alice',data)
            with self.assertRaises(DomainError):self.images.preview('alice',data)
        self.assertEqual(adapter.complete_result.call_count,1)
        with self.store.connect() as db:
            tokens,reserved=db.execute('SELECT tokens,reserved FROM model_connection_tests WHERE id=?',(data['request_id'],)).fetchone()
            self.assertIsNone(tokens);self.assertGreater(reserved,0)

    def test_not_sent_failure_has_zero_charge(self):
        data=self.vision();adapter=self.adapter();adapter.complete_result.side_effect=DomainError('MODEL_REQUEST_NOT_SENT','DNS rejected')
        with patch.object(self.service.models,'adapter',return_value=adapter):
            with self.assertRaises(DomainError):self.images.preview('alice',data)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT tokens FROM model_connection_tests').fetchone()[0],0)

    def test_known_usage_survives_invalid_product_json(self):
        data=self.vision();adapter=self.adapter();adapter.complete_result.return_value=({'wrong':'format'},234,{})
        with patch.object(self.service.models,'adapter',return_value=adapter):
            with self.assertRaises(DomainError):self.images.preview('alice',data)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT tokens FROM model_connection_tests').fetchone()[0],234)

    def test_budget_denial_prevents_network(self):
        data=self.vision()
        with self.store.connect() as db:
            db.execute('INSERT INTO model_connection_tests VALUES(?,?,?,?,?,?,?,?)',(str(uuid4()),'alice',data['connection_id'],__import__('time').time(),3_000_000,None,.000002,'calling'))
        adapter=self.adapter()
        with patch.object(self.service.models,'adapter',return_value=adapter):
            with self.assertRaisesRegex(DomainError,'预算'):self.images.preview('alice',data)
        adapter.complete_result.assert_not_called()


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'Requires a dedicated PostgreSQL test database')
class PostgresProductImageTests(ProductImageTests):
    def setUp(self):
        import psycopg
        self.schema='product_image_test_'+uuid4().hex
        self.base=os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('CREATE SCHEMA '+self.schema)
        self.addCleanup(self.cleanup_schema)
        self.store=Store(self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema)
        self.prepare()

    def cleanup_schema(self):
        import psycopg
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('DROP SCHEMA '+self.schema+' CASCADE')

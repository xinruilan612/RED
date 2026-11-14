"""HTTP product-image auth, CSRF, raw download and confirmed RAG ingestion."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_connected_api import ConnectedHarness
from test_product_images import png
from backend.store import Store
from uuid import uuid4


class ProductImageAPITests(ConnectedHarness,unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.store=Store(Path(temp.name)/'api.sqlite');self.prepare()
        mocked=patch('backend.product_images.local_ocr',return_value=['测试保湿乳','净含量50mL'])
        mocked.start();self.addCleanup(mocked.stop)

    def packet(self):
        return dict(account_id=self.account,request_id=str(uuid4()),filename='p.png',file_base64=png(),mode='local')

    def test_csrf_and_cross_owner_cannot_read_or_upload(self):
        packet=self.packet();url='/api/product-images/preview'
        self.assertEqual(self.client.post(url,json=packet).status_code,403)
        other,csrf,_=self.register('image_other')
        self.assertNotEqual(self.post(url,packet,other,csrf).status_code,200)
        response=self.post(url,packet);self.assertEqual(response.status_code,200,response.text)
        identity=response.json()['id']
        self.assertNotEqual(other.get('/api/product-images/'+identity+'/original').status_code,200)
        self.assertEqual(self.client.get('/api/product-images/'+identity+'/original').status_code,200)

    def test_edited_confirmation_saves_only_once_and_can_be_retrieved(self):
        result=self.post('/api/product-images/preview',self.packet()).json()
        self.assertEqual(self.client.get('/api/knowledge',params={'account_id':self.account}).json(),[])
        data=dict(account_id=self.account,title='测试保湿乳',text='已核对的合成产品资料：保湿乳净含量50mL，型号未知。',confirmed=True)
        url='/api/product-images/'+result['id']+'/confirm'
        a=self.post(url,data);self.assertEqual(a.status_code,200,a.text)
        b=self.post(url,data);self.assertEqual(b.status_code,200,b.text);self.assertEqual(a.json()['id'],b.json()['id'])
        docs=self.client.get('/api/knowledge',params={'account_id':self.account}).json();self.assertEqual(len(docs),1)
        doc=self.client.get('/api/knowledge/'+a.json()['id'],params={'account_id':self.account}).json()
        self.assertEqual(doc['chunks'][0]['text'],data['text'])

    def test_confirmation_requires_checked_review_and_supported_image(self):
        packet=self.packet();packet['filename']='payload.svg'
        self.assertNotEqual(self.post('/api/product-images/preview',packet).status_code,200)
        preview=self.post('/api/product-images/preview',self.packet()).json()
        result=self.post('/api/product-images/'+preview['id']+'/confirm',dict(account_id=self.account,title='产品',text='资料',confirmed=False))
        self.assertNotEqual(result.status_code,200)

    def test_product_image_script_is_served_as_javascript(self):
        response=self.client.get('/product_images.js')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.headers['content-type'].startswith('text/javascript'))

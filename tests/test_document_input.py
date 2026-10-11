"""Local document review flow; synthetic files, temporary databases, no models."""
import base64
import copy
import hashlib
import io
import os
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from backend.api import create_app
from backend.contracts import DomainError
from backend.document_input import normalize_text
from backend.knowledge import Knowledge, parse_file
from backend.operations import Operations
from backend.provider import Config
from backend.store import Store
from test_knowledge_sources import text_pdf


def structured_docx(empty_edges=False):
    ns='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    rel='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    cell=lambda text:'<w:tc><w:p><w:r><w:t>'+text+'</w:t></w:r></w:p></w:tc>'
    values=['','30 mL',''] if empty_edges else ['精华','30 mL','¥129.50']
    xml=f'<w:document xmlns:w="{ns}" xmlns:r="{rel}"><w:body><w:p><w:r><w:t>产品参数</w:t></w:r></w:p><w:tbl><w:tr>'+''.join(map(cell,['产品','规格','价格']))+'</w:tr><w:tr>'+''.join(map(cell,values))+'</w:tr></w:tbl><w:p><w:hyperlink r:id="r1"><w:r><w:t>官方说明</w:t></w:r></w:hyperlink></w:p></w:body></w:document>'
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types/>');z.writestr('word/document.xml',xml)
        z.writestr('word/_rels/document.xml.rels',f'<Relationships><Relationship Id="r1" Type="{rel}/hyperlink" Target="https://example.com/product?size=30&amp;unit=mL" TargetMode="External"/></Relationships>')
    return out.getvalue()


class DocumentInputTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'documents.sqlite')
        self.kb=Knowledge(self.store,use_configured_embeddings=False)
        self.owner='review-owner';self.account=Operations(self.store).read(self.owner)['accounts'][0]['id']

    def source(self,**changes):
        data={'account_id':self.account,'title':'精华产品资料','text':'\ufeff规格\t30 mL\r\n价格 ¥129.50\x00\nhttps://example.com/p?a=1&b=2'}
        data.update(changes);return data

    def confirmed(self,data):
        preview=self.kb.preview(self.owner,data)
        return {**data,'input_review':{'confirmed':True,'source_sha256':preview['source_sha256'],
                'confirmation_id':str(uuid4()),'pages':[{'page':p['page'],'text':p['text']} for p in preview['pages']]}}

    def test_preview_is_read_only_and_normalizes_without_damaging_symbols(self):
        data=self.source();preview=self.kb.preview(self.owner,data)
        self.assertFalse(preview['stored']);self.assertTrue(preview['normalized'])
        self.assertEqual(self.kb.list(self.owner,self.account),[])
        self.assertEqual(preview['pages'][0]['original_text'],data['text'])
        self.assertEqual(preview['pages'][0]['text'],'规格\t30 mL\n价格 ¥129.50\nhttps://example.com/p?a=1&b=2')
        self.assertEqual(normalize_text('±0.5% 👩‍💻 **粗体** | a | b |'),'±0.5% 👩‍💻 **粗体** | a | b |')

    def test_review_keeps_original_bytes_and_retrieves_only_corrected_text(self):
        raw=b'\xef\xbb\xbf'+ '原始价格 ¥129.50\r\n精华 30 mL'.encode('utf-8')
        data=self.source();data.pop('text');data.update(filename='产品.txt',file_base64=base64.b64encode(raw).decode())
        confirmed=self.confirmed(data);confirmed['input_review']['pages'][0]['text']='校对价格 ¥119.50\n精华 30 mL'
        result=self.kb.save(self.owner,confirmed)
        self.assertEqual(self.kb.original(self.owner,self.account,result['id'],1),('产品.txt',raw))
        self.assertEqual(result['fingerprint'],hashlib.sha256(raw).hexdigest())
        text=''.join(p['text'] for p in self.kb.retrieve(self.owner,self.account,'校对价格 精华')['sources'])
        self.assertIn('119.50',text);self.assertNotIn('129.50',text)
        self.assertTrue(result['metadata']['input_review']['confirmed'])

    def test_uncertain_confirmation_retries_same_receipt_without_duplicate_version(self):
        data=self.confirmed(self.source());first=self.kb.save(self.owner,data)
        again=self.kb.save(self.owner,data)
        self.assertEqual((again['id'],again['version']),(first['id'],1))
        self.assertEqual(len(self.kb.list(self.owner,self.account)),1)
        changed=copy.deepcopy(data);changed['input_review']['pages'][0]['text']='不同正文'
        with self.assertRaises(DomainError):self.kb.save(self.owner,changed)

    def test_concurrent_confirmation_has_one_document_and_version(self):
        data=self.confirmed(self.source())
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.kb.save(self.owner,data),range(2)))
        self.assertEqual(results[0]['id'],results[1]['id']);self.assertEqual(results[1]['version'],1)

    def test_update_keeps_old_input_and_repeated_confirmation_does_not_append(self):
        first_data=self.confirmed(self.source());first=self.kb.save(self.owner,first_data)
        second_data=self.confirmed(self.source(document_id=first['id'],expected_version=1,text='新版 50 mL'))
        second=self.kb.save(self.owner,second_data);again=self.kb.save(self.owner,second_data)
        self.assertEqual((second['version'],again['version'],len(again['versions'])),(2,2,2))
        self.assertEqual(self.kb.original(self.owner,self.account,first['id'],1)[1],first_data['text'].encode())
        self.assertEqual(self.kb.original(self.owner,self.account,first['id'],2)[1],b'\xe6\x96\xb0\xe7\x89\x88 50 mL')

    def test_old_confirmation_retry_acknowledges_its_version_not_later_edit(self):
        first_data=self.confirmed(self.source());first=self.kb.save(self.owner,first_data)
        second_data=self.confirmed(self.source(document_id=first['id'],expected_version=1,text='新版 50 mL'))
        second=self.kb.save(self.owner,second_data)
        replayed=self.kb.save(self.owner,first_data)
        receipt=replayed['input_confirmation']
        self.assertEqual((receipt['confirmed_version'],receipt['current_version'],replayed['version']),(1,2,2))
        self.assertTrue(receipt['replayed']);self.assertFalse(first['input_confirmation']['replayed'])
        for key in ('confirmation_id','source_sha256','reviewed_sha256','confirmed_at'):
            self.assertEqual(receipt[key],first['input_confirmation'][key])
        self.assertEqual(replayed['metadata']['input_review']['confirmation_id'],second_data['input_review']['confirmation_id'])
        self.assertEqual(len(replayed['versions']),2)
        self.assertEqual(replayed['chunks'],second['chunks'])

    def test_invalid_review_cannot_enter_knowledge(self):
        confirmed=self.confirmed(self.source())
        invalid=[]
        for key,value in [('confirmed',False),('source_sha256','changed'),('pages',[{'page':999,'text':'wrong'}]),('pages',[{'page':1,'text':''}])]:
            item=copy.deepcopy(confirmed);item['input_review'][key]=value;invalid.append(item)
        item=copy.deepcopy(confirmed);item['text']='changed raw';invalid.append(item)
        for item in invalid:
            with self.subTest(item=item),self.assertRaises(DomainError):self.kb.save(self.owner,item)
        self.assertEqual(self.kb.list(self.owner,self.account),[])

    def test_owner_account_checks_precede_parsing_and_original_download(self):
        confirmed=self.confirmed(self.source());doc=self.kb.save(self.owner,confirmed)
        other=Operations(self.store).read('other')['accounts'][0]['id']
        with patch('backend.document_input.read_input') as parser:
            with self.assertRaises(DomainError):self.kb.preview('other',self.source())
            parser.assert_not_called()
        with self.assertRaises(DomainError):self.kb.original('other',other,doc['id'],1)
        with self.assertRaises(DomainError):self.kb.save('other',confirmed)

    def test_docx_table_rows_links_order_and_units_are_preserved(self):
        pages=parse_file('产品.docx',structured_docx())
        self.assertEqual([p[1] for p in pages[:3]],['产品参数','产品\t规格\t价格','精华\t30 mL\t¥129.50'])
        self.assertEqual(pages[3][1],'官方说明 (https://example.com/product?size=30&unit=mL)')

    def test_docx_empty_edge_cells_keep_column_positions_through_retrieval(self):
        raw=structured_docx(empty_edges=True)
        data=self.source();data.pop('text')
        data.update(filename='空首尾列.docx',file_base64=base64.b64encode(raw).decode())
        preview=self.kb.preview(self.owner,data)
        row=next(p for p in preview['pages'] if p['page']==3)
        self.assertEqual(row['original_text'],'\t30 mL\t')
        self.assertEqual(row['text'],'\t30 mL\t')
        saved=self.kb.save(self.owner,self.confirmed(data))
        self.assertEqual(next(p['text'] for p in saved['chunks'] if p['page']==3),'\t30 mL\t')
        retrieved=self.kb.retrieve(self.owner,self.account,'30 mL')['sources']
        self.assertEqual(next(p['text'] for p in retrieved if p['page']==3),'\t30 mL\t')
        self.assertEqual(self.kb.original(self.owner,self.account,saved['id'],1)[1],raw)

    def test_pdf_preview_retains_page_numbers_and_warns_about_layout(self):
        data=self.source();data.pop('text');data.update(filename='care.pdf',file_base64=base64.b64encode(text_pdf()).decode())
        preview=self.kb.preview(self.owner,data)
        self.assertEqual([p['page'] for p in preview['pages']],[1,2])
        self.assertTrue(any('多栏' in warning for warning in preview['warnings']))
        self.assertEqual(self.kb.list(self.owner,self.account),[])

    def test_failed_parse_keeps_existing_knowledge_unchanged(self):
        first=self.kb.save(self.owner,self.confirmed(self.source()))
        bad=self.source();bad.pop('text');bad.update(filename='broken.pdf',file_base64=base64.b64encode(b'broken').decode())
        with self.assertRaises((ValueError,DomainError)):self.kb.preview(self.owner,bad)
        self.assertEqual(self.kb.list(self.owner,self.account)[0]['id'],first['id'])

    def test_http_preview_csrf_confirm_and_original_download(self):
        app=create_app(self.store,Config(),origin='http://testserver',invite='')
        with TestClient(app) as client:
            csrf=client.get('/api/session').json()['csrf']
            def post(path,data):return client.post(path,json=data,headers={'Origin':'http://testserver','X-CSRF-Token':csrf})
            csrf=post('/api/auth/register',{'username':'documentuser','password':'Long-test-password'}).json()['csrf']
            account=client.get('/api/operations').json()['accounts'][0]['id']
            data=self.source(account_id=account)
            self.assertEqual(client.post('/api/knowledge/preview',json=data).status_code,403)
            preview=post('/api/knowledge/preview',data);self.assertEqual(preview.status_code,200,preview.text)
            self.assertEqual(client.get('/api/knowledge',params={'account_id':account}).json(),[])
            p=preview.json();data['input_review']={'confirmed':True,'source_sha256':p['source_sha256'],'confirmation_id':str(uuid4()),'pages':[{'page':v['page'],'text':v['text']} for v in p['pages']]}
            saved=post('/api/knowledge',data);self.assertEqual(saved.status_code,200,saved.text)
            original=client.get('/api/knowledge/'+saved.json()['id']+'/original',params={'account_id':account,'version':1})
            self.assertEqual(original.status_code,200);self.assertEqual(original.content,data['text'].encode('utf-8'))
            self.assertIn('attachment',original.headers['content-disposition'])


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'PostgreSQL integration requires TEST_DATABASE_URL')
class PostgresDocumentInputTests(DocumentInputTests):
    def setUp(self):
        import psycopg
        self.base=os.environ['TEST_DATABASE_URL'];self.schema='youji_test_'+uuid4().hex
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('CREATE SCHEMA '+self.schema)
        def cleanup():
            with psycopg.connect(self.base,autocommit=True) as db:db.execute('DROP SCHEMA '+self.schema+' CASCADE')
        self.addCleanup(cleanup)
        self.store=Store(self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema)
        self.kb=Knowledge(self.store,use_configured_embeddings=False)
        self.owner='review-owner';self.account=Operations(self.store).read(self.owner)['accounts'][0]['id']

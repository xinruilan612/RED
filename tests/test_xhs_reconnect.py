"""QR validation and reconnect ownership; no external connections."""
import base64
import struct
import unittest
import zlib
from backend.contracts import DomainError
from backend.xhs_local import LocalXHS
import test_xhs_sync as sync_tests
from test_xhs_sync import snapshot


def png():
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
    return 'data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,0,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00\x00'))+chunk(b'IEND',b'')).decode()

class QRTests(unittest.TestCase):
    def test_fixed_get_valid_png_sanitized_response(self):
        client=LocalXHS();calls=[]
        def request(path,data=None):
            calls.append((path,data));return {'img':png(),'timeout':'3m59.99s','is_logged_in':False,'cookie':'SECRET','token':'SECRET'}
        client.request=request;result=client.reconnect()
        self.assertEqual(calls,[('/api/v1/login/qrcode',None)]);self.assertEqual(set(result),{'is_logged_in','img','timeout'});self.assertNotIn('SECRET',str(result))
    def test_rejects_external_svg_corrupt_and_large_images(self):
        for img in ['https://example.com/qr','data:image/svg+xml;base64,AAAA','data:image/png;base64,AAAA','data:image/png;base64,'+'A'*750000,png()[:-4]+'AAAA']:
            client=LocalXHS();client.request=lambda *a:{'img':img,'timeout':'4m0s'}
            with self.assertRaises(DomainError):client.reconnect()
    def test_qr_cannot_post_or_forward_write_route(self):
        client=LocalXHS()
        with self.assertRaises(DomainError):client.request('/api/v1/login/qrcode',{})
        with self.assertRaises(DomainError):client.request('/api/v1/publish',{})
    def test_existing_login_does_not_return_extra_fields(self):
        client=LocalXHS();client.request=lambda *a:{'is_logged_in':True,'img':'SECRET','cookie':'SECRET'}
        self.assertEqual(client.reconnect(),{'is_logged_in':True,'img':None,'timeout':None})

class ReconnectMixin:
    def test_reconnect_pauses_fences_and_preserves_binding(self):
        job=self.sync._claim();self.fake.reconnect=lambda:{'img':png(),'timeout':'4m0s','is_logged_in':False}
        result=self.sync.reconnect(self.owner,self.account);self.assertEqual(result['img'],png())
        self.assertEqual(self.state()['status'],'paused');self.assertFalse(self.state()['enabled']);self.assertEqual(self.state()['source_id'],'source')
        with self.assertRaises(DomainError):self.sync._save(job,snapshot())
        with self.assertRaises(DomainError):self.sync.reconnect('other',self.account)
        self.sync.control(self.owner,self.account,'resume');self.fake.result['identity']['id']='other';self.sync.once()
        self.assertEqual(self.state()['status'],'needs_attention');self.assertEqual(self.state()['counts']['note'],0)

class ReconnectTests(ReconnectMixin,unittest.TestCase):
    setUp=sync_tests.SyncTests.setUp
    prepare=sync_tests.SyncTests.prepare
    tearDown=sync_tests.SyncTests.tearDown
    state=sync_tests.SyncTests.state

@unittest.skipUnless(__import__('os').environ.get('TEST_DATABASE_URL'),'requires actual PostgreSQL')
class PostgresReconnectTests(ReconnectTests):
    setUp=sync_tests.PostgresSyncTests.setUp
    tearDown=sync_tests.PostgresSyncTests.tearDown

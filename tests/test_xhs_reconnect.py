"""QR validation and reconnect ownership; no external connections."""
import base64
import os
import struct
import unittest
from unittest import mock
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

class ConnectorTokenPathTests(unittest.TestCase):
    def test_env_overrides_the_working_directory_default(self):
        with mock.patch.dict(os.environ,{'YOUJI_XHS_TOKEN_FILE':'/tmp/example/control-token'}):
            self.assertEqual(str(LocalXHS().token_file),'/tmp/example/control-token')

    def test_explicit_argument_wins_over_env(self):
        with mock.patch.dict(os.environ,{'YOUJI_XHS_TOKEN_FILE':'/tmp/example/control-token'}):
            self.assertEqual(str(LocalXHS(token_file='/other/control-token').token_file),'/other/control-token')

    def test_missing_token_file_is_actionable_not_a_crash(self):
        client=LocalXHS(token_file='/definitely/missing/control-token')
        with self.assertRaises(DomainError) as caught:client.request('/api/v1/login/status')
        self.assertIn('YOUJI_XHS_TOKEN_FILE',str(caught.exception))

class BridgePortTests(unittest.TestCase):
    def test_default_env_override_and_invalid_values(self):
        from backend import xhs_sync
        self.assertEqual(xhs_sync._bridge_port(18060),18060)
        self.assertEqual(xhs_sync._bridge_port(None),18061)
        with mock.patch.dict(os.environ,{'XHS_BRIDGE_PORT':'18060'}):
            self.assertEqual(xhs_sync._bridge_port(None),18060)
        with mock.patch.dict(os.environ,{'XHS_BRIDGE_PORT':''}):
            self.assertEqual(xhs_sync._bridge_port(None),18061)
        for bad in ('abc','80','70000','18061.5'):
            with mock.patch.dict(os.environ,{'XHS_BRIDGE_PORT':bad}):
                with self.assertRaises(DomainError):xhs_sync._bridge_port(None)

class ReconnectMixin:
    def test_unbound_account_reaches_login_before_first_binding(self):
        """A fresh install must be able to scan a QR: bind needs login, login needed bind."""
        with self.sync.store.connect() as db:
            db.execute('DELETE FROM xhs_sync_links WHERE owner=? AND account_id=?',(self.owner,self.account))
        self.fake.reconnect=lambda:{'img':png(),'timeout':'4m0s','is_logged_in':False}
        self.assertFalse(self.sync.public(self.owner,self.account)['bound'])
        result=self.sync.reconnect(self.owner,self.account)
        self.assertEqual(result['img'],png())
        # Requesting a QR must not silently create a binding; identity is checked at bind time.
        self.assertFalse(self.sync.public(self.owner,self.account)['bound'])
        with self.assertRaises(DomainError):self.sync.reconnect('other',self.account)

    def test_bind_still_requires_a_verified_identity(self):
        with self.sync.store.connect() as db:
            db.execute('DELETE FROM xhs_sync_links WHERE owner=? AND account_id=?',(self.owner,self.account))
        self.fake.identity=lambda:{'id':'','nickname':''}
        with self.assertRaises(DomainError):self.sync.bind(self.owner,self.account)

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

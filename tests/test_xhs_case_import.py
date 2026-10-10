"""Offline bridge tests in SQLite and real PostgreSQL schemas."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from backend.store import Store
from backend.contracts import DomainError
from backend.migrations import upgrade
from backend.operations import Operations
from backend.xhs_sync import XHSSync
from backend.xhs_case_import import XHSCaseImport
from test_xhs_sync import Fake


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'test.sqlite');self.prepare()
    def prepare(self):
        upgrade(self.store);self.owner='owner';self.account=Operations(self.store).read(self.owner)['accounts'][0]['id']
        self.fake=Fake();self.sync=XHSSync(self.store,lambda port:self.fake);self.sync.bind(self.owner,self.account);self.sync.once()
        self.bridge=XHSCaseImport(self.store);self.data={'account_id':self.account,'note_id':'n','permission_confirmed':True}
    def tearDown(self):self.tmp.cleanup()
    def test_import_idempotency_source_and_rag_without_comments_or_network(self):
        with patch('socket.create_connection',side_effect=AssertionError('network forbidden')):
            result=self.bridge.save(self.owner,self.data);again=self.bridge.save(self.owner,self.data)
        self.assertFalse(result['reused']);self.assertTrue(again['reused']);self.assertEqual(result['id'],again['id']);self.assertEqual(again['version'],1)
        case=result['metadata']['research_case']
        self.assertEqual(case['source_method'],'local_browser_mcp');self.assertEqual(case['metrics']['likes'],0)
        self.assertIsNone(case['metrics']['views']);self.assertIsNone(case['metrics']['favorites']);self.assertIsNotNone(case['observed_at'])
        self.assertEqual(case['evidence_role'],'expression_reference');self.assertEqual(result['source_url'],'https://www.xiaohongshu.com/explore/n')
        self.assertEqual(''.join(c['text'] for c in result['chunks']),'body');self.assertNotIn('comment',str(result['chunks']))
        matches=self.bridge.cases.knowledge.retrieve(self.owner,self.account,'body')
        self.assertTrue(matches['sources']);self.assertEqual(matches['sources'][0]['evidence_role'],'expression_reference')
    def test_changed_body_creates_version_same_document(self):
        first=self.bridge.save(self.owner,self.data)
        self.fake.result['notes'][0]['text']='updated body'
        with self.store.connect() as db:db.execute('UPDATE xhs_sync_links SET next_at=0')
        self.sync.once();second=self.bridge.save(self.owner,self.data)
        self.assertEqual(first['id'],second['id']);self.assertEqual(second['version'],2)
        self.assertEqual(self.bridge.cases.knowledge.get_version(self.owner,self.account,first['id'],1)['chunks'][0]['text'],'body')
    def test_ownership_consent_missing_note_and_body(self):
        for owner,data in [('other',self.data),(self.owner,{**self.data,'permission_confirmed':False}),(self.owner,{**self.data,'note_id':'missing'})]:
            with self.assertRaises(DomainError):self.bridge.save(owner,data)
        self.fake.result['notes'][0]['text']=''
        with self.store.connect() as db:db.execute('UPDATE xhs_sync_links SET next_at=0')
        self.sync.once()
        with self.assertRaises(DomainError):self.bridge.save(self.owner,self.data)
        self.assertEqual(self.bridge.cases.list(self.owner,self.account),[])
    def test_retry_after_concurrent_import_reuses_same_version(self):
        original=self.bridge.cases.save
        def concurrent(*args,**kwargs):
            self.bridge.cases.save=original
            original(*args,**{k:v for k,v in kwargs.items() if k!='transaction_guard'})
            return original(*args,**kwargs)
        self.bridge.cases.save=concurrent
        result=self.bridge.save(self.owner,self.data)
        self.assertTrue(result['reused']);self.assertEqual(result['version'],1)
        self.assertEqual(len(self.bridge.cases.list(self.owner,self.account)),1)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'requires actual PostgreSQL')
class PostgresImportTests(ImportTests):
    def setUp(self):
        import psycopg
        self.tmp=tempfile.TemporaryDirectory();self.schema='youji_import_test_'+uuid4().hex;self.base=os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('CREATE SCHEMA '+self.schema)
        self.store=Store(self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema);self.prepare()
    def tearDown(self):
        import psycopg
        self.tmp.cleanup()
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('DROP SCHEMA '+self.schema+' CASCADE')

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4
from backend.store import Store
from backend.migrations import upgrade, MIGRATIONS
from backend.media_templates import catalog, choose
from backend.contracts import DomainError
from tests.test_media_exports import fixture


class MediaCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'db.sqlite')
        upgrade(self.store,MIGRATIONS[:-1])
        self.run=fixture('已确认的正文')
        self.run.context['operations']={'account_id':'account-a'}
        self.save(self.run)
        upgrade(self.store)

    def save(self,run):
        with self.store.connect() as db:
            db.execute('INSERT INTO runs(id,owner,payload) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(run.run_id,run.owner_id,json.dumps(asdict(run))))

    def request(self,action='init',**kw):
        return dict(action=action,idempotency_key=uuid4().hex,draft_ref=self.run.accepted_ref,content_hash=self.run.acceptance['content_hash'],**kw)

    def choose(self,data):
        return choose(self.store,self.run.owner_id,self.run.run_id,data)

    def test_upgrade_preserves_draft_and_read_does_not_rotate(self):
        self.assertEqual(self.store.get(self.run.run_id,self.run.owner_id).drafts,self.run.drafts)
        for _ in range(2):
            result=catalog(self.store,self.run.owner_id,self.run.run_id)
            self.assertEqual(len(result['templates']),8)
            self.assertIsNone(result['selection'])
        self.assertEqual(self.choose(self.request())['template_id'],'xhs-e')
        self.assertEqual(self.choose(self.request())['template_id'],'xhs-e')
        self.assertEqual(self.choose(self.request('next'))['template_id'],'xhs-a')

    def test_manual_persists_and_isolation_and_stale_version(self):
        result=self.choose(self.request('select',template_id='xhs-h'))
        self.assertEqual(catalog(self.store,self.run.owner_id,self.run.run_id)['selection'],result)
        with self.assertRaises(DomainError): catalog(self.store,'other',self.run.run_id)
        with self.assertRaises(DomainError): choose(self.store,'other',self.run.run_id,self.request())
        request=self.request();request['draft_ref']='old'
        with self.assertRaises(DomainError):self.choose(request)
        with self.assertRaises(DomainError):self.choose(self.request('select',template_id='../evil'))
        with self.store.connect() as db:
            db.execute("UPDATE media_templates SET version=999 WHERE id='xhs-e'")
        self.assertNotIn('xhs-e',[t['id'] for t in catalog(self.store,self.run.owner_id)['templates']])

    def test_concurrent_rotation_and_idempotency(self):
        data=self.request('next')
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(self.choose,[data]*4))
        self.assertEqual({r['template_id'] for r in results},{'xhs-e'})
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(self.choose,[self.request('next') for _ in range(4)]))
        self.assertEqual(len({r['template_id'] for r in results}),4)
        with self.assertRaises(DomainError):self.choose({**data,'action':'init'})

    def test_account_and_owner_rotation_independent(self):
        self.choose(self.request())
        for account,owner in [('account-b',self.run.owner_id),('account-a','different-owner')]:
            run=fixture('另一个稿件');run.context['operations']={'account_id':account};run.owner_id=owner
            self.save(run)
            data=dict(action='init',idempotency_key=uuid4().hex,draft_ref=run.accepted_ref,content_hash=run.acceptance['content_hash'])
            self.assertEqual(choose(self.store,owner,run.run_id,data)['template_id'],'xhs-e')

    def test_next_skips_current_manual_selection(self):
        self.choose(self.request())
        self.choose(self.request('select',template_id='xhs-a'))
        self.assertEqual(self.choose(self.request('next'))['template_id'],'xhs-b')
        with self.assertRaises(DomainError):self.choose({**self.request(),'action':[]})

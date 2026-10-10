"""No-network sync tests; PostgreSQL subclass exercises the same persisted fences."""
import copy
import os
import tempfile
import time
import unittest
from pathlib import Path
from uuid import uuid4
from backend.store import Store
from backend.migrations import upgrade
from backend.operations import Operations
from backend.contracts import DomainError
from backend.xhs_local import LocalXHS, normalize_detail
from backend.xhs_sync import XHSSync


def snapshot():
    note=normalize_detail({'note':{'noteId':'n','user':{'userId':'source'},'title':'title','desc':'body','interactInfo':{'likedCount':'0','collectedCount':'1.2万'}},'comments':{'list':[{'id':'c','content':'comment','userInfo':{'nickname':'SENSITIVE_NICKNAME'}}]}},'source','n')
    return dict(identity={'id':'source'},notes=[note],failures=[],observed_at='2026-10-10T00:00:00Z',coverage='partial',
                creator_metrics={'status':'synced','source_id':'source','observed_at':'2026-01-01T00:00:00Z','account':None,
                    'notes':[{'id':'n','visibility':'public','visibility_source':'creator_note_card_no_private_label','metrics':{}}]})

class Fake:
    def __init__(self):self.result=snapshot();self.failure=None
    def identity(self):return {'id':'source'}
    def collect(self,expected_id,limit,check):
        check()
        if self.failure:raise self.failure
        return copy.deepcopy(self.result)

class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'test.sqlite');self.prepare()
    def prepare(self):
        upgrade(self.store);self.owner='owner';self.account=Operations(self.store).read(self.owner)['accounts'][0]['id'];self.fake=Fake();self.sync=XHSSync(self.store,lambda port:self.fake);self.sync.bind(self.owner,self.account)
    def tearDown(self):self.tmp.cleanup()
    def due(self):
        with self.store.connect() as db:db.execute('UPDATE xhs_sync_links SET next_at=0')
    def state(self):return self.sync.public(self.owner,self.account)
    def test_dedup_update_restart_and_partial_preservation(self):
        self.assertTrue(self.sync.once());self.assertFalse(self.sync.once())
        self.assertEqual(self.state()['counts'],{'note':1,'comment':1})
        self.due();self.sync=XHSSync(Store(self.store.path),lambda port:self.fake);self.sync.once()
        self.assertEqual(self.state()['latest_round']['summary']['new_notes'],0)
        self.assertEqual(self.state()['latest_round']['summary']['changed_notes'],0)
        self.fake.result['notes'][0]['metrics']['likes']=2;self.fake.result['notes'][0]['comments']=[]
        self.due();self.sync.once();self.assertEqual(self.state()['latest_round']['summary']['changed_notes'],1)
        self.assertEqual(self.state()['counts']['comment'],1)
    def test_pause_fences_late_result_and_resume(self):
        job=self.sync._claim();self.sync.control(self.owner,self.account,'pause')
        with self.assertRaises(DomainError):self.sync._save(job,snapshot())
        self.assertEqual(self.state()['counts']['note'],0)
        self.sync.control(self.owner,self.account,'resume');self.sync.once();self.assertEqual(self.state()['status'],'synced')
    def test_saved_comments_survive_partial_round_and_are_scoped(self):
        self.sync.once()
        self.fake.result['notes'][0]['comments']=[];self.due();self.sync.once()
        data=self.sync.comments(self.owner,self.account,'n')
        self.assertEqual([c['content'] for c in data['items']],['comment'])
        self.assertLessEqual(data['items'][0]['first_seen'],data['items'][0]['last_seen'])
        self.assertIsNone(data['next_offset'])
        with self.assertRaises(DomainError):self.sync.comments('other',self.account,'n')
        with self.assertRaises(DomainError):self.sync.comments(self.owner,self.account,'missing')
        with self.assertRaises(DomainError):self.sync.comments(self.owner,self.account,'n',-1)
    def test_saved_comments_have_stable_bounded_pages(self):
        self.fake.result['notes'][0]['comments']=[{'id':str(i),'content':str(i)} for i in range(53)]
        self.sync.once()
        first=self.sync.comments(self.owner,self.account,'n');second=self.sync.comments(self.owner,self.account,'n',first['next_offset'])
        self.assertEqual(len(first['items']),50);self.assertEqual(len(second['items']),3)
        self.assertEqual(len({c['id'] for c in first['items']+second['items']}),53)
        self.assertIsNone(second['next_offset'])
    def test_expired_worker_lease_delays_retry_and_rejects_stale_save(self):
        job=self.sync._claim()
        with self.store.connect() as db:db.execute('UPDATE xhs_sync_links SET lease_until=0')
        self.assertIsNone(self.sync._claim())
        with self.assertRaises(DomainError):self.sync._save(job,snapshot())
        self.assertEqual(self.state()['status'],'retrying')
    def test_identity_change_and_repeated_transport_failure_stop(self):
        self.fake.failure=DomainError('XHS_TRANSPORT','private error')
        for _ in range(3):self.due();self.sync.once()
        self.assertFalse(self.state()['enabled']);self.assertNotIn('private error',str(self.state()))
        self.sync.control(self.owner,self.account,'resume');self.fake.failure=DomainError('XHS_IDENTITY_CHANGED','changed');self.sync.once()
        self.assertFalse(self.state()['enabled']);self.assertEqual(self.state()['counts']['note'],0)
    def test_owner_isolation_and_no_shared_session_binding(self):
        with self.assertRaises(DomainError):self.sync.public('other',self.account)
        other=Operations(self.store).read('other')['accounts'][0]['id']
        with self.assertRaises(DomainError):self.sync.bind('other',other)
    def test_unknown_counts_and_sensitive_fields(self):
        self.sync.once();n=self.sync.records(self.owner,self.account)[0]
        self.assertEqual(n['metrics']['likes'],0);self.assertIsNone(n['metrics']['favorites']);self.assertIsNone(n['metrics']['views'])
        self.assertNotIn('SENSITIVE_NICKNAME',str(self.state()))
    def test_round_identity_mismatch_saves_nothing(self):
        self.fake.result['identity']['id']='other';self.sync.once();self.assertEqual(self.state()['counts']['note'],0)
    def test_client_rejects_write_route_without_network(self):
        with self.assertRaises(DomainError):LocalXHS().request('/api/v1/publish',{})
    def test_collect_rechecks_identity_and_never_saves_foreign_note(self):
        client=LocalXHS();calls=[]
        def request(path,data=None):
            calls.append(path)
            if path.endswith('status'):return {'is_logged_in':True,'user_id':'source' if len(calls)==1 else 'other'}
            return {'data':{'feeds':[]}}
        client.request=request
        with self.assertRaises(DomainError):client.collect('source')
        with self.assertRaises(DomainError):normalize_detail({'note':{'noteId':'n','user':{'userId':'other'}}},'source','n')

@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'requires actual PostgreSQL')
class PostgresSyncTests(SyncTests):
    def setUp(self):
        import psycopg
        self.tmp=tempfile.TemporaryDirectory();self.schema='youji_sync_test_'+uuid4().hex;self.base=os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('CREATE SCHEMA '+self.schema)
        self.store=Store(self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema);self.prepare()
    def tearDown(self):
        import psycopg
        self.tmp.cleanup()
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('DROP SCHEMA '+self.schema+' CASCADE')

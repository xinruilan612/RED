"""Creator visibility fences API data without deleting persisted audit history."""
import copy
import json
import os
import unittest
from unittest.mock import patch
import test_xhs_sync as sync_tests
from backend.contracts import DomainError
from backend.xhs_sync import creator_snapshot
from backend.xhs_case_import import XHSCaseImport


def creator():
    return {'status':'synced','source_id':'source','observed_at':'2026-01-01T00:00:00Z',
            'source_updated_at':None,'source_method':'creator_browser_dom',
            'account':{'period_start':'2025-12-25','period_end':'2025-12-31','period_days':7,
                       'metrics':{'exposure':100,'views':0,'cover_ctr':2.5,'favorites':'1.2万'}},
            'notes':[{'id':'n','title':'Public title','visibility':'public','visibility_source':'creator_note_card_no_private_label',
                      'metrics':{'views':11,'comments':2,'likes':0,'favorites':None,'shares':None},
                      'source_url':'https://www.xiaohongshu.com/explore/n?xsec_token=SECRET'}],
            'error':None,'cookie':'SECRET'}


class CreatorPersistenceTests(unittest.TestCase):
    setUp=sync_tests.SyncTests.setUp
    prepare=sync_tests.SyncTests.prepare
    tearDown=sync_tests.SyncTests.tearDown
    state=sync_tests.SyncTests.state
    due=sync_tests.SyncTests.due

    def stored_count(self,kind):
        with self.store.connect() as db:
            return db.execute('SELECT COUNT(*) FROM xhs_sync_entities WHERE kind=?',(kind,)).fetchone()[0]

    def test_separate_public_note_snapshot_and_no_account_aggregate(self):
        self.fake.result['creator_metrics']=creator();self.sync.once()
        state=self.state();metrics=state['creator_metrics'];note=self.sync.records(self.owner,self.account)[0]
        self.assertIsNone(metrics['account'])
        self.assertIsNone(note['metrics']['views']);self.assertEqual(note['creator_metrics']['metrics']['views'],11)
        self.assertIsNone(note['creator_metrics']['metrics']['favorites'])
        self.assertEqual(state['counts'],{'note':1,'comment':1})
        self.assertEqual(state['creator_last_success'],metrics)
        self.assertFalse(metrics['official_api']);self.assertIsNone(metrics['source_updated_at'])
        self.assertNotIn('SECRET',str(state)+str(note));self.assertNotIn('cookie',str(metrics))

    def test_failed_creator_retains_history_and_saves_new_comments(self):
        self.fake.result['creator_metrics']=creator();self.sync.once();before=self.state()['creator_last_success']
        self.fake.result['creator_metrics']={'status':'failed','observed_at':'2026-01-02T00:00:00Z','error':'CREATOR_LOGIN_REQUIRED','account':{'metrics':{'views':999}}}
        self.fake.result['notes'][0]['comments'].append({'id':'new','content':'new comment'})
        self.due();self.sync.once();state=self.state()
        self.assertEqual(state['status'],'partial');self.assertEqual(state['counts']['comment'],2)
        self.assertEqual(state['creator_metrics']['status'],'failed');self.assertIsNone(state['creator_metrics']['account'])
        self.assertEqual(state['creator_last_success'],before)
        self.assertEqual(self.sync.records(self.owner,self.account)[0]['creator_metrics']['metrics']['views'],11)

    def test_foreign_creator_data_hidden_but_comments_still_persist(self):
        raw=creator();raw['source_id']='other';self.fake.result['creator_metrics']=raw;self.sync.once()
        state=self.state();self.assertEqual(state['creator_metrics']['error'],'XHS_IDENTITY_CHANGED')
        self.assertIsNone(state['creator_last_success']);self.assertEqual(state['counts']['comment'],0)
        self.assertEqual(self.stored_count('comment'),1)
        self.assertEqual(state['status'],'partial');self.assertEqual(self.sync.records(self.owner,self.account),[])

    def test_bad_creator_payload_cannot_abort_valid_comment_round(self):
        self.fake.result['creator_metrics']={'status':'synced','source_id':'source','observed_at':'not a time SECRET'}
        self.sync.once();state=self.state()
        self.assertEqual(self.stored_count('note'),1);self.assertEqual(self.stored_count('comment'),1)
        self.assertEqual(state['creator_metrics']['error'],'XHS_CREATOR_RESPONSE')
        self.assertNotIn('SECRET',str(state))

    def test_round_snapshots_are_immutable_and_owner_scoped(self):
        self.fake.result['creator_metrics']=creator();self.sync.once()
        self.fake.result['creator_metrics']['notes'][0]['metrics']['views']=12
        self.fake.result['creator_metrics']['account']['metrics']['views']=20
        self.due();self.sync.once()
        with self.store.connect() as db:
            rows=db.execute('SELECT payload FROM xhs_sync_rounds WHERE owner=? AND account_id=? ORDER BY observed_at',(self.owner,self.account)).fetchall()
        self.assertEqual([json.loads(r[0])['creator_metrics']['account']['metrics']['views'] for r in rows],[0,20])
        with self.assertRaises(DomainError):self.sync.public('other',self.account)
        with self.assertRaises(DomainError):self.sync.records('other',self.account)

    def test_changed_binding_fences_all_late_data(self):
        job=self.sync._claim();result=copy.deepcopy(self.fake.result);result['creator_metrics']=creator()
        with self.store.connect() as db:db.execute("UPDATE xhs_sync_links SET source_id='other'")
        with self.assertRaises(DomainError):self.sync._save(job,result)
        self.assertEqual(self.state()['counts'],{'note':0,'comment':0});self.assertIsNone(self.state()['creator_last_success'])

    def test_unknown_numeric_values_and_removed_metrics(self):
        raw=creator();raw['account']['metrics'].update(exposure=True,views=-1,cover_ctr=float('nan'),shares='100',followers_gained=1,follows_added=2,unfollows=3,profile_visitors=4)
        values=creator_snapshot(raw,'source')['account']['metrics']
        self.assertTrue(all(values[k] is None for k in ('exposure','views','cover_ctr','shares')))
        self.assertTrue(all(k not in values for k in ('followers_gained','follows_added','unfollows','profile_visitors')))

    def test_private_and_unknown_creator_notes_excluded_before_storage(self):
        raw=creator();raw['notes'] += [
            {'id':'private_note','title':'PRIVATE TITLE','visibility':'private','metrics':{'views':7}},
            {'id':'old_note','title':'UNKNOWN TITLE','metrics':{'views':8}}]
        self.fake.result['creator_metrics']=raw;self.sync.once();state=self.state()
        self.assertEqual([n['id'] for n in state['creator_metrics']['notes']],['n'])
        self.assertNotIn('PRIVATE TITLE',str(state));self.assertNotIn('UNKNOWN TITLE',str(state))
        self.assertEqual(self.stored_count('creator_note'),1)

    def test_legacy_snapshot_cannot_escape_via_status_records_comments_or_import(self):
        self.fake.result['creator_metrics']=creator();self.sync.once()
        # Simulate a historical snapshot predating explicit visibility markers.
        with self.store.connect() as db:
            rows=db.execute('SELECT kind,id,payload FROM xhs_sync_entities').fetchall()
            for kind,identity,payload in rows:
                value=json.loads(payload)
                if kind=='creator_account':
                    for n in value['notes']:n.pop('visibility',None);n.pop('visibility_source',None)
                if kind=='creator_note':value.pop('visibility',None);value.pop('visibility_source',None)
                db.execute('UPDATE xhs_sync_entities SET payload=? WHERE kind=? AND id=?',(json.dumps(value),kind,identity))
        state=self.state()
        self.assertEqual(state['latest_round']['notes'],[]);self.assertEqual(state['creator_last_success']['notes'],[])
        self.assertEqual(state['creator_metrics']['notes'],[]);self.assertEqual(self.sync.records(self.owner,self.account),[])
        self.assertEqual(state['counts'],{'note':0,'comment':0})
        self.assertNotIn('Public title',str(state))
        with self.assertRaises(DomainError):self.sync.comments(self.owner,self.account,'n')
        with self.assertRaises(DomainError):XHSCaseImport(self.store).save(self.owner,{'account_id':self.account,'note_id':'n','permission_confirmed':True})
        self.assertEqual(self.stored_count('note'),1);self.assertEqual(self.stored_count('comment'),1)
        self.due();self.sync.once();self.assertEqual(len(self.sync.records(self.owner,self.account)),1)

    def test_later_private_transition_revokes_record_comments_and_import(self):
        self.fake.result['creator_metrics']=creator();self.sync.once()
        bridge=XHSCaseImport(self.store);data={'account_id':self.account,'note_id':'n','permission_confirmed':True}
        bridge.save(self.owner,data)
        self.fake.result['creator_metrics']['notes']=[];self.due();self.sync.once()
        self.assertEqual(self.sync.records(self.owner,self.account),[])
        self.assertEqual(self.state()['latest_round']['notes'],[])
        with self.assertRaises(DomainError):self.sync.comments(self.owner,self.account,'n')
        with self.assertRaises(DomainError):bridge.save(self.owner,data)
        self.assertEqual(self.stored_count('note'),1)

    def test_import_rechecks_public_visibility_in_save_transaction(self):
        self.fake.result['creator_metrics']=creator();self.sync.once()
        bridge=XHSCaseImport(self.store);save=bridge.cases.save
        def revoke(*args,**kwargs):
            with self.store.connect() as db:
                raw=creator();raw['notes']=[]
                db.execute("UPDATE xhs_sync_entities SET payload=? WHERE kind='creator_account'",(json.dumps(raw),))
            return save(*args,**kwargs)
        with patch.object(bridge.cases,'save',revoke),self.assertRaises(DomainError):
            bridge.save(self.owner,{'account_id':self.account,'note_id':'n','permission_confirmed':True})
        self.assertEqual(bridge.cases.list(self.owner,self.account),[])


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'requires actual PostgreSQL')
class PostgresCreatorPersistenceTests(CreatorPersistenceTests):
    setUp=sync_tests.PostgresSyncTests.setUp
    tearDown=sync_tests.PostgresSyncTests.tearDown

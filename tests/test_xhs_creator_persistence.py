"""Optional creator DOM snapshots cannot overwrite or break comment sync."""
import copy
import json
import os
import unittest
import test_xhs_sync as sync_tests
from backend.contracts import DomainError
from backend.xhs_sync import creator_snapshot


def creator():
    return {'status':'synced','source_id':'source','observed_at':'2026-01-01T00:00:00Z',
            'source_updated_at':None,'source_method':'creator_browser_dom',
            'account':{'period_start':'2025-12-25','period_end':'2025-12-31','period_days':7,
                       'metrics':{'exposure':100,'views':0,'cover_ctr':2.5,'favorites':'1.2万'}},
            'notes':[{'id':'n','metrics':{'views':11,'comments':2,'likes':0,'favorites':None,'shares':None},
                      'source_url':'https://www.xiaohongshu.com/explore/n?xsec_token=SECRET'}],
            'error':None,'cookie':'SECRET'}


class CreatorPersistenceTests(unittest.TestCase):
    setUp=sync_tests.SyncTests.setUp
    prepare=sync_tests.SyncTests.prepare
    tearDown=sync_tests.SyncTests.tearDown
    state=sync_tests.SyncTests.state
    due=sync_tests.SyncTests.due

    def test_separate_snapshot_and_records_keep_unknown_and_no_tokens(self):
        self.fake.result['creator_metrics']=creator();self.sync.once()
        state=self.state();metrics=state['creator_metrics'];note=self.sync.records(self.owner,self.account)[0]
        self.assertEqual(metrics['account']['metrics']['exposure'],100)
        self.assertEqual(metrics['account']['metrics']['views'],0)
        self.assertEqual(metrics['account']['metrics']['cover_ctr'],2.5)
        self.assertIsNone(metrics['account']['metrics']['favorites'])
        self.assertIsNone(metrics['account']['metrics']['comments'])
        self.assertIsNone(note['metrics']['views']);self.assertEqual(note['creator_metrics']['metrics']['views'],11)
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

    def test_foreign_creator_data_is_rejected_without_losing_comments(self):
        raw=creator();raw['source_id']='other';self.fake.result['creator_metrics']=raw;self.sync.once()
        state=self.state();self.assertEqual(state['creator_metrics']['error'],'XHS_IDENTITY_CHANGED')
        self.assertIsNone(state['creator_last_success']);self.assertEqual(state['counts']['comment'],1)
        self.assertEqual(state['status'],'partial')
        self.assertIsNone(self.sync.records(self.owner,self.account)[0]['creator_metrics'])

    def test_bad_creator_payload_cannot_abort_valid_comment_round(self):
        self.fake.result['creator_metrics']={'status':'synced','source_id':'source','observed_at':'not a time SECRET'}
        self.sync.once();state=self.state()
        self.assertEqual(state['counts']['note'],1);self.assertEqual(state['counts']['comment'],1)
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
        self.assertEqual(self.state()['counts'],{'note':0,'comment':0})
        self.assertIsNone(self.state()['creator_last_success'])

    def test_bad_numeric_values_stay_unknown(self):
        raw=creator();raw['account']['metrics'].update(exposure=True,views=-1,cover_ctr=float('nan'),shares='100')
        values=creator_snapshot(raw,'source')['account']['metrics']
        self.assertTrue(all(values[k] is None for k in ('exposure','views','cover_ctr','shares')))

    def test_displays_extra_account_metrics_and_private_notes_are_retained(self):
        raw=creator();raw['creator_account_id']='short123'
        raw['account'].update(period_display='12-25 至 12-31',metric_displays={'favorites':'1.2万','cookie':'SECRET'})
        raw['account']['metrics'].update(video_completion_rate=33.3,followers_gained=-1,follows_added=2,unfollows=0,profile_visitors=3)
        raw['notes'].append({'id':'private_note','title':'仅自己可见笔记','published_display':'昨天',
                             'metrics':{'views':7},'metric_displays':{'views':'7'}})
        self.fake.result['creator_metrics']=raw;self.sync.once();state=self.state();saved=state['creator_metrics']
        self.assertEqual(saved['creator_account_id'],'short123')
        self.assertEqual(saved['account']['period_display'],'12-25 至 12-31')
        self.assertEqual(saved['account']['metrics']['video_completion_rate'],33.3)
        self.assertEqual(saved['account']['metrics']['profile_visitors'],3)
        self.assertEqual(saved['account']['metrics']['followers_gained'],-1)
        self.assertEqual(saved['account']['metric_displays']['favorites'],'1.2万')
        self.assertIsNone(saved['account']['metrics']['favorites'])
        self.assertEqual(saved['notes'][1]['id'],'private_note');self.assertEqual(saved['notes'][1]['title'],'仅自己可见笔记')
        self.assertEqual(len(state['creator_last_success']['notes']),2)
        self.assertEqual(state['counts']['note'],1)
        self.assertNotIn('SECRET',str(saved))


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'requires actual PostgreSQL')
class PostgresCreatorPersistenceTests(CreatorPersistenceTests):
    setUp=sync_tests.PostgresSyncTests.setUp
    tearDown=sync_tests.PostgresSyncTests.tearDown

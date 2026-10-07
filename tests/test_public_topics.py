"""Public references stay account-scoped and never impersonate outcome history."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.contracts import DomainError
from backend.public_topics import PublicTopics,PublicClient,normalize,count,merge_samples,apply_public_topic_action

class MemoryOperations:
    def __init__(self): self.states={}
    def read(self,owner):
        return copy.deepcopy(self.states.setdefault(owner,dict(version=0,accounts=[dict(id=owner+'account',platform='xiaohongshu',profile={})],publications=[])))
    def command(self,owner,command,internal=False):
        assert internal
        state=self.read(owner)
        if state['version']!=command['version']: raise DomainError('VERSION_CONFLICT','changed')
        apply_public_topic_action(state,command['action'],command['payload']);state['version']+=1;self.states[owner]=state
class FakeClient:
    def __init__(self):self.calls=[]
    def search(self,keyword,sort):
        self.calls.append(sort)
        return {'feeds':[{'id':'abc123456789','xsecToken':'private-token','noteCard':{'displayTitle':'摄影','interactInfo':{'likedCount':'1.2万'}}}]}
    def detail(self,identity,token):return {'note':{'title':'摄影','desc':'详细正文','interact_info':{'liked_count':'12001'}}}
    def status(self):return {'is_logged_in':True}
    def qrcode(self):return {'img':'data:image/png;base64,fixture'}
class PublicTopicTests(unittest.TestCase):
    def setUp(self):self.ops=MemoryOperations();self.client=FakeClient();self.service=PublicTopics(self.ops,self.client)
    def data(self,**kwargs):return dict(account_id='uaccount',version=self.ops.read('u')['version'],**kwargs)
    def test_search_mixed_deduplicated_and_no_fake_labels(self):
        result=self.service.search('u',self.data(keyword='摄影'))
        self.assertEqual(self.client.calls,['综合','最新','最多点赞']);self.assertEqual(len(result['samples']),1)
        row=result['samples'][0];self.assertEqual(row['counts']['likes'],12000);self.assertIsNone(row['counts']['views']);self.assertFalse(row['prediction_eligible']);self.assertNotIn('xsec_token',row)
        self.assertEqual(self.ops.read('u')['publications'],[])
    def test_read_performs_no_network(self):
        self.service.read('u','uaccount');self.assertEqual(self.client.calls,[])
    def test_owner_and_account_isolation(self):
        with self.assertRaises(DomainError):self.service.read('v','uaccount')
        self.assertEqual(self.service.read('v','vaccount')['samples'],[])
    def test_stale_version_no_network(self):
        self.service.search('u',self.data(keyword='摄影'))
        self.client.calls=[]
        with self.assertRaises(DomainError):self.service.search('u',dict(account_id='uaccount',version=0,keyword='a'))
        self.assertEqual(self.client.calls,[])
    def test_manual_import_refresh_remove(self):
        r=self.service.import_samples('u',self.data(samples=[dict(url='https://www.xiaohongshu.com/explore/abc123456789',title='手动正文',counts={'likes':1})]))
        self.assertEqual(r['samples'][0]['source'],'manual_public')
        r=self.service.refresh('u',self.data(sample_id='abc123456789'))
        self.assertEqual(r['samples'][0]['body'],'详细正文');self.assertEqual(len(r['samples'][0]['observations']),2)
        self.assertEqual(self.service.remove('u',self.data(sample_id='abc123456789'))['samples'],[])
    def test_source_failure_does_not_erase_saved_data(self):
        self.service.search('u',self.data(keyword='摄影'))
        def failed(*args):raise DomainError('PUBLIC_SOURCE_UNAVAILABLE','down')
        self.client.search=failed
        with self.assertRaises(DomainError):self.service.search('u',self.data(keyword='a'))
        self.assertEqual(len(self.service.read('u','uaccount')['samples']),1)
    def test_url_and_counts_validation(self):
        for value in ['http://127.0.0.1/x','https://evil.com/explore/abc123456789','file:///x']:
            with self.assertRaises(DomainError):normalize(dict(url=value),'manual_public')
        self.assertIsNone(count(True));self.assertIsNone(count(-1));self.assertIsNone(count('未知'));self.assertEqual(count('3千'),3000)
    def test_detail_retained_by_sparse_search(self):
        old=normalize(dict(id='abc123456789',body='full'),'public_detail');new=normalize(dict(id='abc123456789'),'public_search')
        self.assertEqual(merge_samples([old],[new])[0]['body'],'full')
    def test_only_allowlisted_connector_endpoints(self):
        with self.assertRaises(DomainError):PublicClient().request('/publish',{})
    def test_connector_bound_to_configured_owner(self):
        with tempfile.TemporaryDirectory() as folder,patch('backend.public_topics.CONNECTOR_DIR',Path(folder)):
            service=PublicTopics(self.ops)
            with self.assertRaises(DomainError):service.check_connector_owner('u')
            (Path(folder)/'owner-id').write_text('u')
            service.check_connector_owner('u')
            with self.assertRaises(DomainError):service.check_connector_owner('v')
    def test_explicit_login_only(self):
        self.assertTrue(self.service.connect('u',dict(account_id='uaccount',mode='status'))['is_logged_in'])
        with self.assertRaises(DomainError):self.service.connect('u',dict(account_id='uaccount',mode='publish'))
    def test_version_race_does_not_commit_stale_search(self):
        original=self.client.search
        def racing(keyword,sort):
            state=self.ops.read('u');state['version']+=1;self.ops.states['u']=state;return original(keyword,sort)
        self.client.search=racing
        with self.assertRaises(DomainError):self.service.search('u',self.data(keyword='摄影'))
        self.assertEqual(self.service.read('u','uaccount')['samples'],[])
    def test_official_detail_envelope_and_shared_count(self):
        self.service.search('u',self.data(keyword='摄影'))
        self.client.detail=lambda *a:{'feed_id':'abc123456789','data':{'note':{'noteId':'abc123456789','title':'官方详情','desc':'正文','time':1702195200000,'interactInfo':{'sharedCount':'20'},'imageList':[{'urlDefault':'https://example.com/image.jpg'}]},'comments':{'list':[]}}}
        row=self.service.refresh('u',self.data(sample_id='abc123456789'))['samples'][0]
        self.assertEqual(row['body'],'正文');self.assertEqual(row['counts']['shares'],20);self.assertEqual(row['content_status'],'detail_read');self.assertEqual(len(row['image_urls']),1)
    def test_malformed_detail_preserves_existing_snapshot(self):
        self.service.import_samples('u',self.data(samples=[dict(url='https://www.xiaohongshu.com/explore/abc123456789',body='已有正文')]))
        before=self.service.read('u','uaccount')
        for invalid in ({},{'data':None},{'data':{'note':{}}},{'data':{'note':{'noteId':'another123','title':'wrong'}}}):
            self.client.detail=lambda *a:invalid
            with self.assertRaises(DomainError):self.service.refresh('u',self.data(sample_id='abc123456789'))
            self.assertEqual(self.service.read('u','uaccount'),before)
    def test_malformed_feeds_do_not_crash_or_erase(self):
        self.service.search('u',self.data(keyword='摄影'))
        for invalid in (None,{},'bad',3):
            self.client.search=lambda *a:{'feeds':invalid}
            self.assertEqual(len(self.service.search('u',self.data(keyword='摄影'))['samples']),1)
        self.client.search=lambda *a:{'feeds':[None,{'id':'abc123456789','noteCard':None}]}
        self.assertEqual(len(self.service.search('u',self.data(keyword='摄影'))['samples']),1)
    def test_count_overflow_missing_and_bad_types(self):
        for bad in ('9'*400,'9'*30+'万',float('inf'),float('nan'),10**30,{},[]):self.assertIsNone(count(bad))
        row=normalize(dict(id='abc123456789',title=None,desc=None,user='bad',imageList=[None,1,{}],interactInfo=['bad']),'public_search')
        self.assertEqual(row['body'],'');self.assertEqual(row['title'],'');self.assertIsNone(row['counts']['likes'])
    def test_search_summary_and_cover_are_explicit(self):
        row=normalize(dict(id='abc123456789',noteCard={'displayTitle':'题目','cover':{'urlDefault':'https://example.com/cover.jpg'}}),'public_search')
        self.assertEqual(row['content_status'],'search_summary');self.assertEqual(row['body'],'');self.assertEqual(len(row['image_urls']),1)
    def test_summary_cannot_replace_read_body(self):
        old=normalize(dict(id='abc123456789',body='完整正文'),'public_detail')
        new=normalize(dict(id='abc123456789',body='搜索摘要'),'public_search')
        row=merge_samples([old],[new])[0]
        self.assertEqual(row['body'],'完整正文');self.assertEqual(row['content_status'],'detail_read')

class PublicClientTimeoutTests(unittest.TestCase):
    def test_detail_gets_bounded_longer_timeout_without_changing_search(self):
        from unittest.mock import MagicMock
        response=MagicMock()
        response.__enter__.return_value.read.return_value=b'{"success":true,"data":{}}'
        opener=MagicMock();opener.open.return_value=response
        with patch('backend.public_topics.urllib.request.build_opener',return_value=opener):
            client=PublicClient();client.detail('abc123456789','secret')
            self.assertEqual(opener.open.call_args.kwargs['timeout'],30)
            client.search('test','综合')
            self.assertEqual(opener.open.call_args.kwargs['timeout'],15)
    def test_timeout_is_not_automatically_retried(self):
        from unittest.mock import MagicMock
        opener=MagicMock();opener.open.side_effect=TimeoutError('private upstream detail')
        with patch('backend.public_topics.urllib.request.build_opener',return_value=opener):
            with self.assertRaises(DomainError) as caught:
                PublicClient().detail('abc123456789','secret')
            self.assertEqual(opener.open.call_count,1)
            self.assertNotIn('private upstream',str(caught.exception))

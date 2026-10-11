import json
import tempfile
import unittest
from pathlib import Path
from backend.knowledge import Knowledge
from backend.creation_taxonomy import classify_task, classify_document, taxonomy
from backend.contracts import DomainError
from backend.operations import Operations
from backend.store import Store


class RecordingVectors:
    """Deterministic provider double tests filtering; NOT quality evidence."""
    max_chunks=256
    minimum_similarity=.4
    def __init__(self):self.inputs=[]
    def encode(self,texts):
        self.inputs.append(texts)
        return [[1.,.1] for _ in texts]


class OriginalRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'test.sqlite')
        self.owner='owner';self.account=Operations(self.store).read(self.owner)['accounts'][0]['id']
        self.provider=RecordingVectors();self.kb=Knowledge(self.store,self.provider)
        self.target={'domains':['beauty'],'channel':'xiaohongshu','format':'note'}
    def tearDown(self):self.tmp.cleanup()
    def save(self,name,kind,domain='beauty',form='note',channel='xiaohongshu',text=None):
        return self.kb.save(self.owner,{'account_id':self.account,'title':name,'text':text or name+' 原创写作开篇节奏结构表达。','classification':{'domains':[domain],'channel':channel,'format':form,'material_type':kind}})
    def test_filters_precede_embedding_and_facts_ignore_channel(self):
        yes=self.save('美妆笔记样例','example');self.save('摄影笔记不可召回','example','photography')
        self.save('美妆视频不可召回','example',form='video_script')
        fact=self.save('A1面霜产品资料','fact',channel='any',text='A1面霜产品资料：净含量30毫升。')
        self.save('B2面霜错误产品','fact',text='B2面霜产品资料：净含量80毫升。')
        self.save('通用方法','method','general','any','any')
        result=self.kb.grouped_retrieve(self.owner,self.account,'A1面霜产品资料',self.target)
        self.assertEqual([yes['id']],[s['document_id'] for s in result['groups']['examples']])
        self.assertEqual([fact['id']],[s['document_id'] for s in result['groups']['facts']])
        self.assertEqual(len(result['groups']['methods']),1)
        encoded=str(self.provider.inputs)
        self.assertNotIn('摄影笔记不可召回',encoded);self.assertNotIn('美妆视频不可召回',encoded)
        self.assertIsNone(result['filters']['facts']['channel'])
        self.assertEqual(fact['chunks'][0]['classification']['material_type'],'fact')
    def test_missing_examples_never_pad_and_no_model_never_fake_vectors(self):
        self.save('摄影','example','photography')
        result=self.kb.grouped_retrieve(self.owner,self.account,'面霜',self.target)
        self.assertEqual(result['groups']['examples'],[])
        self.assertIn('NO_MATCHING_EXAMPLES',[g['code'] for g in result['gaps']])
        kb=Knowledge(self.store,use_configured_embeddings=False)
        result=kb.grouped_retrieve(self.owner,self.account,'面霜',self.target)
        self.assertEqual(result['engine'],'unavailable');self.assertEqual(result['sources'],[])
    def test_explicit_multidomain_and_form(self):
        target=classify_task({'domains':['digital','photography'],'format':'video_script'},{'topic':'面霜'})
        self.assertEqual(target['domains'],['digital','photography']);self.assertEqual(target['origin'],'user')
        self.assertEqual(classify_task(None,{'topic':'白衬衫穿搭'})['domains'],['apparel'])
        with self.assertRaises(DomainError):classify_task(None,{'topic':'苹果怎么选'})
        self.assertGreater(len(taxonomy()['domains']),15)
        for word,domain in [('唇釉','beauty'),('三脚架','photography'),('边桌','furniture')]:
            self.assertIn(domain,classify_task(None,{'topic':word+'规格介绍'})['domains'])
    def test_video_metadata_inference_preserves_real_forms(self):
        for case in ({'content_kind':'transcript'}, {'source_method':'local_browser_video_description'},
                     {'provenance':{'content_type':'video','body_kind':'video_description'}}):
            label=classify_document(None,'摄影相机介绍','摄影样例',{'research_case':{'platform':'xiaohongshu','evidence_role':'expression_reference',**case}})
            self.assertEqual(label['format'],'video_script')
            self.assertEqual(label['material_type'],'example')
        label=classify_document(None,'摄影相机介绍','摄影样例',{'research_case':{'platform':'xiaohongshu','content_kind':'text','evidence_role':'expression_reference'}})
        self.assertEqual(label['format'],'note')

    def test_explicit_private_and_unreviewed_cases_never_enter_grouped_sources(self):
        for i,extra in enumerate(({'provenance':{'visibility':'private'}},{'review_required':True},{'content_kind':'lead'})):
            self.kb.save(self.owner,{'account_id':self.account,'title':'美妆隐私'+str(i),'text':'面霜结构表达'+str(i),
                'classification':dict(self.target,material_type='example')},source_type='research_case',
                metadata={'research_case':{'evidence_role':'expression_reference',**extra},'retrieval_eligible':True})
        result=self.kb.grouped_retrieve(self.owner,self.account,'面霜',self.target)
        self.assertEqual(result['sources'],[])
        self.assertEqual(self.provider.inputs,[])

    def test_classification_only_case_edit_preserves_source_and_audit(self):
        doc=self.kb.save(self.owner,{'account_id':self.account,'title':'美妆视频参考','text':'面霜包装描述与表达顺序。'},
            source_type='research_case',source_url='https://www.xiaohongshu.com/explore/abc',
            metadata={'evidence_role':'expression_reference','research_case':{'evidence_role':'expression_reference',
                'source_method':'manual_import','provenance':{'visibility':'public'},'platform':'xiaohongshu'}})
        old=self.kb.get_version(self.owner,self.account,doc['id'],1)
        new=self.kb.classify(self.owner,self.account,doc['id'],1,dict(self.target,format='video_script',material_type='example'))
        self.assertEqual(new['version'],2);self.assertEqual(new['fingerprint'],old['fingerprint'])
        self.assertEqual(new['metadata']['research_case'],old['metadata']['research_case'])
        self.assertEqual(new['chunks'][0]['text'],old['chunks'][0]['text'])
        self.assertEqual(self.kb.get_version(self.owner,self.account,doc['id'],1),old)
        self.assertEqual(new['metadata']['classification']['origin'],'user')
        with self.assertRaises(DomainError) as error:
            self.kb.classify(self.owner,self.account,doc['id'],2,dict(self.target,material_type='fact'))
        self.assertEqual(error.exception.code,'CASE_EDIT_REQUIRED')
        with self.assertRaises(DomainError):self.kb.classify(self.owner,self.account,doc['id'],1,dict(self.target,material_type='example'))
        other=Operations(self.store).read('other')['accounts'][0]['id']
        with self.assertRaises(DomainError):self.kb.classify('other',other,doc['id'],2,dict(self.target,material_type='example'))
        self.assertEqual(self.kb.get(self.owner,self.account,doc['id'])['version'],2)

    def test_owner_scope_and_budget(self):
        for i in range(6):self.save('面霜'+str(i),'example',text='面霜'+str(i)+'开篇表达'*200)
        result=self.kb.grouped_retrieve(self.owner,self.account,'面霜',self.target)
        self.assertLessEqual(len(result['groups']['examples']),3)
        self.assertLessEqual(result['context_chars'],5200)
        other=Operations(self.store).read('other')['accounts'][0]['id']
        self.assertEqual(self.kb.grouped_retrieve('other',other,'面霜',self.target)['sources'],[])
    def test_backfill_creates_versions_and_keeps_history(self):
        doc=self.save('历史美妆样例','example')
        with self.store.connect() as db:
            row=db.execute('SELECT metadata FROM knowledge_versions WHERE document_id=?',(doc['id'],)).fetchone()
            meta=json.loads(row[0]);meta.pop('classification');meta['evidence_role']='expression_reference'
            db.execute('UPDATE knowledge_versions SET metadata=? WHERE document_id=?',(json.dumps(meta),doc['id']))
        self.assertEqual(self.kb.backfill_classifications(self.owner,self.account)['updated'],1)
        new=self.kb.get(self.owner,self.account,doc['id'])
        self.assertEqual(new['version'],2);self.assertEqual(new['metadata']['classification']['origin'],'inferred')
        self.assertNotIn('classification',self.kb.get_version(self.owner,self.account,doc['id'],1)['metadata'])
        self.assertEqual(self.kb.backfill_classifications(self.owner,self.account)['updated'],0)

if __name__=='__main__':unittest.main()

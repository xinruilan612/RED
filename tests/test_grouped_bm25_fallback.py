"""Real lexical retrieval regressions; vector doubles test routing, not quality."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from backend.accounts import PROFILE_FIELDS
from backend.contracts import DomainError
from backend.embeddings import EmbeddingUnavailable
from backend.knowledge import Knowledge, bm25_scores
from backend.operations import Operations
from backend.store import Store


class VectorDouble:
    max_chunks=256
    minimum_similarity=.4

    def encode(self,texts):
        return [[1.,0.] for _ in texts]


class GroupedBM25FallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'test.sqlite')
        self.owner='owner';self.account=Operations(self.store).read(self.owner)['accounts'][0]['id']
        self.kb=Knowledge(self.store,use_configured_embeddings=False)
        self.target={'domains':['beauty'],'channel':'xiaohongshu','format':'note'}

    def tearDown(self):
        self.tmp.cleanup()

    def save(self,title,kind='fact',text=None,domain='beauty',channel='xiaohongshu',form='note',metadata=None,owner=None,account=None,**extra):
        return self.kb.save(owner or self.owner,{
            'account_id':account or self.account,'title':title,
            'text':text or title+' 美妆 图文笔记 原创写作 开篇 节奏 结构 表达。A1面霜产品资料：净含量30毫升。',
            'classification':{'domains':[domain],'channel':channel,'format':form,'material_type':kind},**extra},metadata=metadata)

    def retrieve(self,query='A1面霜产品资料',**kwargs):
        return self.kb.grouped_retrieve(self.owner,self.account,query,self.target,**kwargs)

    def test_missing_model_uses_real_bm25_in_all_three_filtered_groups(self):
        expected={'methods':self.save('通用方法','method',domain='general',channel='any',form='any'),
                  'examples':self.save('美妆笔记样例','example'),
                  'facts':self.save('A1面霜产品资料',channel='any',form='any')}
        # Exercise the default-install path without relying on machine model state.
        self.kb.use_configured_embeddings=True
        with patch('backend.embeddings.configured_embeddings',return_value=(None,'未配置本地语义模型')):
            result=self.retrieve()
        self.assertEqual(result['engine'],'filtered-bm25-zh-bigram-v1')
        self.assertFalse(result['insufficient'])
        self.assertIn('BM25',result['embedding_note'])
        self.assertIn('VECTOR_UNAVAILABLE',[gap['code'] for gap in result['gaps']])
        for group,doc in expected.items():
            sources=result['groups'][group]
            self.assertEqual([s['document_id'] for s in sources],[doc['id']])
            self.assertIsNone(sources[0]['semantic_score'])
            self.assertEqual(sources[0]['retrieval_mode'],'bm25')
            self.assertGreater(sources[0]['score'],0)
            self.assertIn(sources[0]['text'],doc['chunks'][0]['text'])
            self.assertEqual(result['filters'][group]['vector_candidate_count'],0)
            self.assertEqual(result['filters'][group]['lexical_candidate_count'],1)

    def test_fallback_scores_only_authorized_reviewed_matching_candidates(self):
        example=self.save('准许样例','example');fact=self.save('准许事实')
        self.save('跨领域','example',domain='photography')
        self.save('跨形式','example',form='video_script')
        self.save('未知渠道样例','example',channel='any')
        self.save('通用领域不能充当样例','example',domain='general')
        self.save('错误型号',text='B2面霜产品资料：净含量80毫升。')
        self.save('型号子串',text='XA1面霜产品资料：净含量90毫升。')
        self.save('跨领域事实',domain='photography')
        self.save('不可检索',metadata={'retrieval_eligible':False})
        self.save('表达参考不能借成事实',metadata={'evidence_role':'expression_reference'})
        for kind in ('fact','example'):
            for name,case in (
                    ('私密',{'provenance':{'visibility':'private'}}),
                    ('好友可见',{'provenance':{'visibility':'friends_only'}}),
                    ('待审核',{'review_required':True}),('线索',{'content_kind':'lead'})):
                self.save(name+kind,kind,metadata={'research_case':case})
        foreign=Operations(self.store).read('other')['accounts'][0]['id']
        self.save('其他用户事实',owner='other',account=foreign)
        ops=Operations(self.store)
        state=ops.command(self.owner,dict(action='save_account',key=str(uuid4()),version=ops.read(self.owner)['version'],
            payload=dict(id='',name='隔离账号',platform='xiaohongshu',profile={**{key:'' for key in PROFILE_FIELDS},'weekly_frequency':3})))
        self.save('同用户另一账号事实',account=state['accounts'][-1]['id'])
        with patch('backend.knowledge.bm25_scores',wraps=bm25_scores) as rank:
            result=self.retrieve()
        self.assertEqual({s['document_id'] for s in result['sources']},{example['id'],fact['id']})
        ranked_ids={row[1] for call in rank.call_args_list for row in call.args[1]}
        self.assertEqual(ranked_ids,{example['id'],fact['id']})
        self.assertEqual(result['filters']['examples']['candidate_count'],1)
        self.assertEqual(result['filters']['facts']['candidate_count'],1)

    def test_fallback_keeps_selected_documents_active_versions_and_owner_scope(self):
        selected=self.save('已选择');self.save('未选择')
        changed=self.save('旧版相关')
        self.save('新版无关',text='烤箱预热温度与时间。',document_id=changed['id'],expected_version=1)
        deleted=self.save('已删除');self.kb.delete(self.owner,self.account,deleted['id'],1)
        result=self.retrieve(document_ids=[selected['id']],include_references=False)
        self.assertEqual([s['document_id'] for s in result['sources']],[selected['id']])
        self.assertEqual(result['sources'][0]['version'],1)
        result=self.retrieve(include_references=False)
        self.assertNotIn(changed['id'],[s['document_id'] for s in result['sources']])
        self.assertNotIn(deleted['id'],[s['document_id'] for s in result['sources']])
        self.assertEqual(self.retrieve(document_ids=[],include_references=False)['sources'],[])
        foreign=Operations(self.store).read('other')['accounts'][0]['id']
        doc=self.save('外部事实',owner='other',account=foreign)
        with self.assertRaises(DomainError):self.retrieve(document_ids=[doc['id']])
        with self.assertRaises(DomainError):self.kb.grouped_retrieve('other',self.account,'面霜',self.target)

    def test_disabled_groups_and_no_lexical_matches_never_get_padded(self):
        self.save('有匹配事实');self.save('有匹配样例','example')
        result=self.retrieve(include_facts=False,include_references=False)
        self.assertEqual(result['sources'],[])
        self.assertTrue(all(value['retrieval_mode']=='disabled' for value in result['filters'].values()))
        self.assertEqual(self.retrieve('数据库索引优化原理',include_references=False)['sources'],[])
        unknown=self.save('主题元数据不能伪造正文匹配','example',text='zyxwv abcdef ghijkl',domain='gardening')
        result=self.kb.grouped_retrieve(self.owner,self.account,'园艺',dict(self.target,domains=['gardening']))
        self.assertEqual(result['filters']['examples']['candidate_count'],1)
        self.assertEqual(result['groups']['examples'],[])
        self.assertNotIn(unknown['id'],[s['document_id'] for s in result['sources']])

    def test_successful_vector_zero_matches_does_not_trigger_bm25(self):
        self.save('词项高度相关事实')
        provider=VectorDouble();self.kb.embedding_provider=provider
        with patch.object(provider,'encode',side_effect=lambda texts:[[1.,0.]]+[[0.,1.] for _ in texts[1:]]), \
                patch('backend.knowledge.bm25_scores',side_effect=AssertionError('不得补齐正常向量空结果')):
            result=self.retrieve(include_references=False)
        self.assertEqual(result['sources'],[])
        self.assertEqual(result['engine'],'filtered-local-vector-rerank-v1')
        self.assertNotIn('VECTOR_UNAVAILABLE',[gap['code'] for gap in result['gaps']])

    def test_late_batch_embedding_failure_recomputes_whole_group_lexically(self):
        first=self.save('第一份事实');second=self.save('第二份事实')
        provider=VectorDouble();provider.max_chunks=1;self.kb.embedding_provider=provider
        with patch.object(provider,'encode',side_effect=[[[1.,0.],[1.,0.]],EmbeddingUnavailable('测试向量故障')]) as encode:
            result=self.retrieve(include_references=False)
        self.assertEqual(encode.call_count,2)
        self.assertEqual({s['document_id'] for s in result['sources']},{first['id'],second['id']})
        self.assertTrue(all(s['semantic_score'] is None and s['retrieval_mode']=='bm25' for s in result['sources']))
        self.assertEqual(result['engine'],'filtered-bm25-zh-bigram-v1')
        self.assertEqual(result['filters']['facts']['vector_candidate_count'],0)
        self.assertEqual(result['filters']['facts']['lexical_candidate_count'],2)

    def test_one_failed_group_has_accurate_mixed_engine_and_per_source_labels(self):
        self.save('方法','method');self.save('样例','example');self.save('事实')
        provider=VectorDouble();self.kb.embedding_provider=provider
        def encode(texts):
            if texts[0].startswith('美妆'):raise EmbeddingUnavailable('样例组测试故障')
            return [[1.,0.] for _ in texts]
        with patch.object(provider,'encode',side_effect=encode):result=self.retrieve()
        self.assertEqual(result['engine'],'filtered-local-vector-bm25-fallback-v1')
        for group in ('methods','facts'):
            self.assertEqual(result['groups'][group][0]['retrieval_mode'],'vector')
            self.assertIsNotNone(result['groups'][group][0]['semantic_score'])
        self.assertEqual(result['groups']['examples'][0]['retrieval_mode'],'bm25')
        self.assertIsNone(result['groups']['examples'][0]['semantic_score'])
        self.assertEqual([g['group'] for g in result['gaps'] if g['code']=='VECTOR_UNAVAILABLE'],['examples'])

    def test_fallback_preserves_group_document_and_context_limits(self):
        for kind in ('method','example','fact'):
            for index in range(6):
                self.save(kind+str(index),kind,text=kind+str(index)+'A1面霜产品资料 美妆 图文笔记 原创写作 开篇 节奏 结构 表达。'*100)
        result=self.retrieve()
        self.assertLessEqual(result['context_chars'],5200)
        for group,limit in (('methods',2),('examples',3),('facts',4)):
            sources=result['groups'][group]
            self.assertLessEqual(len(sources),limit)
            self.assertEqual(len(sources),len({s['document_id'] for s in sources}))
            self.assertTrue(all(len(s['text'])<=700 for s in sources))


if __name__=='__main__':unittest.main()

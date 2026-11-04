import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.embeddings import EmbeddingUnavailable, LocalEmbeddings, validated_vectors
from backend.knowledge import Knowledge
from backend.operations import Operations
from backend.store import Store


class FixtureEmbedding:
    """Vectors test routing/fusion only; not evidence of semantic model quality."""
    max_chunks=256
    minimum_similarity=0.35
    def encode(self,texts):
        return [[1,0] if ('保湿' in t or '肌肤水润' in t) else [0,1] for t in texts]


class HybridRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'rag.sqlite')
        self.account=Operations(self.store).read('owner')['accounts'][0]['id']
        self.kb=Knowledge(self.store,embedding_provider=FixtureEmbedding())

    def tearDown(self):self.temp.cleanup()

    def test_semantic_recall_without_lexical_overlap_and_frozen_version(self):
        first=self.kb.save('owner',{'account_id':self.account,'title':'保养说明','text':'肌肤水润依赖正确使用乳霜。'})
        self.kb.save('owner',{'account_id':self.account,'title':'机器资料','text':'数据库事务隔离与计算机程序设计。'})
        result=self.kb.retrieve('owner',self.account,'保湿')
        self.assertEqual(result['engine'],'hybrid-bm25-local-rrf-v1')
        self.assertEqual(len(result['sources']),1)
        self.assertIsNone(result['sources'][0]['lexical_rank'])
        self.assertEqual(result['sources'][0]['document_id'],first['id'])
        self.kb.save('owner',{'account_id':self.account,'title':'替换内容','text':'计算机课程说明。','document_id':first['id'],'expected_version':1})
        self.assertTrue(self.kb.retrieve('owner',self.account,'保湿')['insufficient'])

    def test_foreign_and_deleted_content_never_sent_to_embedding(self):
        other=Operations(self.store).read('other')['accounts'][0]['id']
        self.kb.save('other',{'account_id':other,'title':'保养','text':'肌肤水润是个人资料。'})
        mine=self.kb.save('owner',{'account_id':self.account,'title':'保养','text':'保湿护理需要留意产品成分。'})
        self.kb.delete('owner',self.account,mine['id'],1)
        with patch.object(self.kb.embedding_provider,'encode') as encode:
            self.assertTrue(self.kb.retrieve('owner',self.account,'保湿')['insufficient'])
            encode.assert_not_called()

    def test_unavailable_or_over_limit_honestly_returns_bm25(self):
        self.kb.save('owner',{'account_id':self.account,'title':'保养','text':'保湿护理需要留意产品成分。'})
        with patch.object(self.kb.embedding_provider,'encode',side_effect=EmbeddingUnavailable('模型不可用')):
            result=self.kb.retrieve('owner',self.account,'保湿')
        self.assertEqual(result['engine'],'bm25-zh-bigram-v1')
        self.assertEqual(result['embedding_note'],'模型不可用')
        self.kb.embedding_provider.max_chunks=0
        self.assertEqual(self.kb.retrieve('owner',self.account,'保湿')['engine'],'bm25-zh-bigram-v1')

    def test_bad_vectors_and_missing_local_model_are_rejected(self):
        for values in ([[math.nan,1]],[[0,0]],[[1],[1,2]],[['not-number']],[]):
            with self.assertRaises(EmbeddingUnavailable):validated_vectors(values,max(1,len(values)))
        with self.assertRaises(EmbeddingUnavailable):LocalEmbeddings('/does/not/exist')

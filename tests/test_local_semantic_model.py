"""Real local model acceptance, not fixture vectors or paid inference."""
import tempfile
import unittest
from pathlib import Path
from backend.embeddings import LocalEmbeddings
from backend.knowledge import Knowledge, tokens
from backend.operations import Operations
from backend.store import Store

MODEL=Path(__file__).resolve().parents[1]/'runtime/models/bge-small-zh-v1.5'

@unittest.skipUnless((MODEL/'youji-model-manifest.json').is_file(),'Install optional pinned local model first')
class RealLocalSemanticTests(unittest.TestCase):
    def test_real_chinese_semantic_recall_without_shared_bigrams(self):
        query='面部干燥怎么缓解'
        relevant='使用保湿乳液有助于肌肤水润。'
        self.assertFalse(set(tokens(query)) & set(tokens(relevant)))
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'real-rag.sqlite')
            account=Operations(store).read('owner')['accounts'][0]['id']
            kb=Knowledge(store,embedding_provider=LocalEmbeddings(str(MODEL)))
            wanted=kb.save('owner',dict(account_id=account,title='护理说明',text=relevant))
            kb.save('owner',dict(account_id=account,title='车辆资料',text='汽车发动机的日常维修。'))
            result=kb.retrieve('owner',account,query)
            self.assertEqual(result['engine'],'hybrid-bm25-local-rrf-v1')
            self.assertEqual(result['sources'][0]['document_id'],wanted['id'])
            self.assertIsNone(result['sources'][0]['lexical_rank'])
            self.assertGreater(result['sources'][0]['semantic_score'],0.4)
            self.assertEqual(len(result['sources']),1)

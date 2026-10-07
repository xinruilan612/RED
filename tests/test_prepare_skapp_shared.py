import copy
from pathlib import Path
import tempfile
import unittest
from scripts.prepare_skapp_shared import prepare,MODEL_NAME

class SharedPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'cover.png').write_bytes(b'fixture-encoder-stub-only')
        self.data=dict(data_scope='licensed_public',dataset_license='test permission declaration',platform='xiaohongshu',target_metric='views',window_hours=24,records=[dict(id='1',text='摄影教程',profile='新手摄影',author_id='public-author',profile_observed_at='2020-01-01T00:00:00Z',published_at='2020-01-02T00:00:00Z',observed_at='2020-01-03T00:00:00Z',value=12,source_url='https://example.org/1',image_path='cover.png')])
    def tearDown(self):self.temp.cleanup()
    def encode(self,texts,images):return dict(model=MODEL_NAME,text_vectors=[[1]+[0]*511 for _ in texts],image_vectors=[[0,1]+[0]*510 for _ in images])
    def test_same_encoder_shared_contract(self):
        result=prepare(self.data,self.root,self.encode)
        self.assertFalse(result['synthetic']);self.assertEqual(result['model_scope'],'shared');self.assertEqual(len(result['records'][0]['visual']),512);self.assertNotIn('image_path',result['records'][0]);self.assertNotIn('scope_digest',result)
    def test_private_or_missing_license_rejected(self):
        for change in ({'data_scope':'private'},{'dataset_license':''}):
            with self.assertRaises(ValueError):prepare(dict(self.data,**change),self.root,self.encode)
    def test_missing_label_future_profile_and_path_escape_rejected(self):
        for change in ({'value':None},{'profile_observed_at':'2021-01-01T00:00:00Z'},{'image_path':'../outside.png'}):
            data=copy.deepcopy(self.data);data['records'][0].update(change)
            with self.assertRaises(ValueError):prepare(data,self.root,self.encode)

    def test_synthetic_marker_is_preserved(self):
        self.assertTrue(prepare(dict(self.data,synthetic=True),self.root,self.encode)['synthetic'])

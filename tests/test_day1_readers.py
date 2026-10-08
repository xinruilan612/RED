"""A three-reader pilot must preserve incomplete real response collection."""
import tempfile
import unittest
from pathlib import Path
from scripts.brand_blindtest import generate, summarize, DIMENSIONS

class DayOneReadersTests(unittest.TestCase):
    def test_three_files_balanced_and_two_responses_do_not_impute_third(self):
        case={'product':'鼠标','audience':'学生','goal':'了解','facts':['USB接收器'],'sources':[{'title':'来源','url':'https://example.com'}],'constraints':['不虚构']}
        with tempfile.TemporaryDirectory() as folder:
            mapping=generate(case,'普通真实稿','系统真实稿',folder,count=3,seed=21)
            self.assertEqual(sorted(p.name for p in Path(folder).glob('*.html')),['P01-试读.html','P02-试读.html','P03-试读.html'])
            self.assertIn(sum(p['labels']['A']=='system' for p in mapping['participants'].values()),(1,2))
            responses=[]
            for pid in ('P01','P02'):
                answers={'preference':'tie','preference_reason':'测试占位，仅用于单元测试'}
                for label in ('A','B'):
                    answers.update({label+'_'+key:'3' for key in DIMENSIONS})
                    answers.update({label+'_message':'测试回答',label+'_reason':'测试理由'})
                responses.append({'participant':pid,'draft_hashes':mapping['participants'][pid]['draft_hashes'],'answers':answers})
            result=summarize(mapping,responses)
            self.assertEqual(result['sample_size'],2)
            self.assertEqual(result['missing_participants'],['P03'])
            self.assertEqual(len(result['scores']['system']['interest']),2)
            self.assertEqual(summarize(mapping,[])['sample_size'],0)

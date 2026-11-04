"""Public report fixture tests; no real ratings, models or credentials."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from scripts.build_final_study_report import build_report,sha

class FinalStudyReportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.receipts=self.root/'runtime';self.receipts.mkdir()
        self.public=self.root/'public';self.blind=self.root/'blind';self.dataset=self.root/'tasks.json'
        tasks=[{'id':'T'+str(i),'input':{'topic':'公开资料构造任务'+str(i),'audience':'普通读者','material':'给定事实，不可编造',
                  'creation':{'word_count':300}}} for i in range(6)]
        self.dataset.write_text(json.dumps({'items':tasks}))
        cases=[];cumulative=10000
        for i in range(7):
            task_id='T'+str(i//2);group='A' if i%2==0 else 'E';identity=task_id+'-'+group
            completed=i<6;tokens=100 if completed else 50;reserve=0 if completed else 2000
            cumulative+=tokens*8+reserve
            case={'id':identity,'task_id':task_id,'arm':group,'elapsed_seconds':1.5,'completed':completed,'cumulative_upper_micro':cumulative}
            cases.append(case)
            receipt={'api_key':'fixture-only','context':{'password':'sensitive'},'calls':[
                {'stage':'body' if completed else 'strategy','tokens':tokens,'status':'validated','prompt_version':'fixture-v1','input_hash':'abc'}],
                'drafts':[{'content':{'selected_title':'标题','body':'正文内容','cta':'互动','tags':['标签']}}] if completed else [],'review':{'decision':'approved'}}
            if not completed:receipt['calls'].append({'stage':'hook','tokens':None,'status':'failed','error':'offline unknown fixture'})
            (self.receipts/(identity+'.json')).write_text(json.dumps(receipt))
        summary={'cases':cases,'experiment':{'task_ids':[task['id'] for task in tasks],'groups':['A','E'],
                    'provenance':{'dataset_sha256':sha(self.dataset.read_bytes())}},'scope':'公开资料构造，未做人审',
                 'source_model':'fixture','initial_upper_micro':10000,'cumulative_upper_micro':cumulative,'stop_reason':'unknown_usage_stop'}
        (self.receipts/'summary.json').write_text(json.dumps(summary))
        for name in ('private-state.json','credentials.key','study.sqlite'):(self.receipts/name).write_text('must-never-copy')
    def build(self):return build_report(self.receipts,self.dataset,self.public,self.blind,source_commit='fixture-commit')
    def test_all_preregistered_cells_failures_cost_and_character_counts_preserved(self):
        report=self.build();self.assertEqual(report['registered_cells'],12)
        self.assertEqual((report['draft_cells'],report['failed_cells'],report['not_run_cells']),(6,1,5))
        self.assertEqual(report['cost_upper_micro']['known_new'],5200)
        self.assertEqual(report['cost_upper_micro']['unknown_reserved'],2000)
        self.assertEqual(report['cases'][0]['title_characters'],2)
        self.assertEqual(report['cases'][0]['body_characters'],4)
        self.assertEqual(report['cases'][0]['cta_characters'],2)
        self.assertIsNone(report['quality_conclusion']);self.assertFalse(report['has_human_quality_scores'])
        self.assertIn('approved不等于', (self.public/'RESULTS.md').read_text())
        self.assertIn('fixture-v1',json.dumps(report))
    def test_only_sanitized_receipts_published_and_each_reviewer_zip_excludes_mapping(self):
        self.build()
        self.assertEqual(len(list((self.public/'receipts').glob('*.json'))),7)
        for path in self.public.rglob('*'):
            if path.is_file():
                self.assertNotIn('fixture-only',path.read_text())
                self.assertNotIn('must-never-copy',path.read_text())
        for archive_file in self.blind.glob('*-独立评审.zip'):
            with zipfile.ZipFile(archive_file) as archive:
                self.assertEqual(set(archive.namelist()),{'articles.html','scores.csv'})
                page=archive.read('articles.html').decode()
                self.assertNotIn('同一虚构任务',page)
                self.assertNotIn('虚构任务只核对',page)
                self.assertIn('开发者不得作为独立评委',page)
                self.assertEqual(page.count('<article>'),6)
                self.assertIn('下载我的评分CSV',page)
                self.assertFalse(any('mapping' in name for name in archive.namelist()))
                self.assertNotIn('"group"',page)
        self.assertTrue((self.blind/'researcher-private/mapping.json').exists())
        self.assertEqual(len(list(self.blind.glob('*-独立评审.zip'))),3)
    def test_missing_receipt_or_changed_dataset_refuses_silent_incomplete_evidence(self):
        (self.receipts/'T0-A.json').unlink()
        with self.assertRaises(ValueError):self.build()
        self.dataset.write_text('{"items":[]}')
        with self.assertRaises(ValueError):self.build()

if __name__=='__main__':unittest.main()

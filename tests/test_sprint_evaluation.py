"""Statistical tooling fixtures only; generated scores are NOT user evidence."""
import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('sprint_evaluation',Path(__file__).resolve().parents[1]/'scripts'/'sprint_evaluation.py')
e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)


class SprintEvaluationTests(unittest.TestCase):
    def data(self):
        return {'tasks':[{'task_id':'private-task','brief':'相同需求和事实核对资料',
             'articles':[{'group':group,'text':'虚构测试正文 <script>unsafe</script> '+str(i)} for i,group in enumerate(e.GROUPS)]}]}

    def mapping(self):
        return {'reviewer_ids':['r1','r2'],'articles':{f'{task}-{group}':{'task_id':task,'group':group} for task in ('t1','t2') for group in e.GROUPS}}

    def scores(self):
        return [{'article_id':article,'reviewer_id':reviewer,**{m:('3' if group['group']=='A' else '4') for m in e.METRICS}} for article,group in self.mapping()['articles'].items() for reviewer in ('r1','r2')]

    def test_blind_package_separates_mapping_randomizes_and_escapes(self):
        with tempfile.TemporaryDirectory() as temp:
            result=e.blind_package(self.data(),temp,3,7)
            self.assertEqual(result['status'],'awaiting_human_scores')
            secret=json.loads((Path(temp)/'researcher-private/mapping.json').read_text())
            self.assertEqual(len(secret['articles']),5)
            orders=[]
            for folder in sorted((Path(temp)/'reviewers').iterdir()):
                page=(folder/'articles.html').read_text()
                self.assertNotIn('private-task',page)
                self.assertNotIn('"group"',page)
                self.assertNotIn('<script>',page)
                self.assertIn('&lt;script&gt;',page)
                scores=e.read_csv(folder/'scores.csv')
                self.assertTrue(all(row[m]=='' for row in scores for m in e.METRICS))
                orders.append([row['article_id'] for row in scores])
            self.assertGreater(len({tuple(order) for order in orders}),1)
            with self.assertRaises(ValueError):e.blind_package(self.data(),temp)

    def test_incomplete_groups_and_empty_articles_are_rejected(self):
        for data in ({'tasks':[]},{'tasks':[{'task_id':'t','articles':[]}]}, {'tasks':[{'task_id':'t','articles':[{'group':g,'text':''} for g in e.GROUPS]}]}):
            with tempfile.TemporaryDirectory() as temp,self.assertRaises(ValueError):e.blind_package(data,temp)

    def test_empty_scores_cannot_become_zero_or_improvement(self):
        report=e.aggregate_scores(self.mapping(),[],100)
        self.assertEqual(report['status'],'awaiting_human_scores')
        self.assertEqual(len(report['missing_rows']),20)
        self.assertIsNone(report['group_summaries']['factuality']['A']['mean'])
        self.assertIsNone(report['paired_comparisons']['E-A/factuality']['mean_difference'])
        self.assertIsNone(report['paired_comparisons']['E-A/factuality']['ci95'])

    def test_bootstrap_unit_is_task_and_duplicate_raters_are_not_extra_tasks(self):
        report=e.aggregate_scores(self.mapping(),self.scores(),200)
        pair=report['paired_comparisons']['E-A/completeness']
        self.assertEqual(pair['task_count'],2)
        self.assertEqual(pair['mean_difference'],1)
        self.assertEqual(pair['ci95'],[1,1])
        self.assertEqual(report['bootstrap']['unit'],'task')
        self.assertEqual(report['status'],'scored_complete')
        self.assertEqual(e.clustered_ci([1],100),None)

    def test_pairing_requires_same_rater_and_missing_cells_are_reported(self):
        rows=[{'article_id':'t1-A','reviewer_id':'r1','completeness':'1'},
              {'article_id':'t1-E','reviewer_id':'r2','completeness':'5'}]
        report=e.aggregate_scores(self.mapping(),rows,100)
        self.assertEqual(report['paired_comparisons']['E-A/completeness']['task_count'],0)
        self.assertEqual(len(report['missing_cells']),8)
        self.assertEqual(report['status'],'scored_partial')

    def test_invalid_duplicate_and_out_of_range_scores_rejected(self):
        for rows in ([{'article_id':'unknown','reviewer_id':'r1'}],self.scores()+self.scores()[:1],
                     [{'article_id':'t1-A','reviewer_id':'r1','completeness':value} for value in ('NaN',)],
                     [{'article_id':'t1-A','reviewer_id':'r1','completeness':'0'}],
                     [{'article_id':'t1-A','reviewer_id':'r1','completeness':'3.5'}]):
            with self.assertRaises(ValueError):e.aggregate_scores(self.mapping(),rows,100)

    def test_fixed_seven_class_metrics_and_independent_kappa(self):
        rows=[{'gold':label,'predicted':label,'annotator1':label,'annotator2':label,'domain':'fixture'} for label in e.LABELS]
        report=e.structure_metrics(rows)
        self.assertEqual(report['macro_f1'],1)
        self.assertEqual(report['agreement']['cohen_kappa'],1)
        self.assertEqual(report['domains']['fixture']['rows'],7)
        rows[0]['predicted']='PROBLEM'
        report=e.structure_metrics(rows)
        self.assertEqual(report['per_label']['HOOK']['recall'],0)
        self.assertEqual(report['per_label']['PROBLEM']['precision'],.5)
        self.assertLess(report['macro_f1'],1)

    def test_empty_annotations_and_degenerate_kappa_remain_unscored(self):
        for rows in ([],[{'gold':'','predicted':'','annotator1':'','annotator2':''}]):
            report=e.structure_metrics(rows)
            self.assertIsNone(report['macro_f1'])
            self.assertIsNone(report['agreement']['cohen_kappa'])
        self.assertIsNone(e.structure_metrics([{'annotator1':'HOOK','annotator2':'HOOK'}])['agreement']['cohen_kappa'])
        with self.assertRaises(ValueError):e.structure_metrics([{'gold':'WRONG','predicted':'CTA'}])
        with self.assertRaises(ValueError):e.structure_metrics([{'article_id':'p1','paragraph_id':'1'}]*2)

    def test_explicit_two_groups_and_four_group_practice_require_complete_registration(self):
        for selected in [('A','E'),('A','B','C','D')]:
            with self.subTest(selected=selected),tempfile.TemporaryDirectory() as temp:
                data=self.data();data['tasks'][0]['articles']=[a for a in data['tasks'][0]['articles'] if a['group'] in selected]
                with self.assertRaises(ValueError):e.blind_package(data,temp)
                result=e.blind_package(data,temp,groups=selected)
                self.assertEqual(result['groups'],list(selected))
                mapping=json.loads((Path(temp)/'researcher-private/mapping.json').read_text())
                self.assertEqual(mapping['controls']['registered_groups'],list(selected))
                self.assertIn('练习包',mapping['scope'])
        with tempfile.TemporaryDirectory() as temp,self.assertRaises(ValueError):
            data=self.data();data['tasks'][0]['articles']=data['tasks'][0]['articles'][:4]
            e.blind_package(data,temp,groups=('A','E'))

    def test_two_group_aggregation_has_no_phantom_arms_and_missing_ratings_stay_null(self):
        mapping=self.mapping();mapping['groups']=['A','E'];mapping['articles']={key:value for key,value in mapping['articles'].items() if value['group'] in ('A','E')}
        rows=[row for row in self.scores() if row['article_id'] in mapping['articles']]
        report=e.aggregate_scores(mapping,rows,100)
        self.assertEqual(set(report['group_summaries']['coherence']),{'A','E'})
        self.assertEqual(report['paired_comparisons']['E-A/coherence']['task_count'],2)
        self.assertFalse(any(key.startswith('B-') for key in report['paired_comparisons']))
        blank=e.aggregate_scores(mapping,[],100)
        self.assertIsNone(blank['group_summaries']['coherence']['E']['mean'])
        self.assertIsNone(blank['paired_comparisons']['E-A/coherence']['ci95'])
        mapping['articles'].pop('t1-E')
        with self.assertRaises(ValueError):e.aggregate_scores(mapping,[],100)

    def test_templates_have_no_scores_or_fake_tasks(self):
        with tempfile.TemporaryDirectory() as temp:
            e.templates(temp)
            self.assertEqual(json.loads((Path(temp)/'articles-input-template.json').read_text())['tasks'],[])
            self.assertEqual(e.read_csv(Path(temp)/'structure-annotations-template.csv'),[])
            self.assertEqual(json.loads((Path(temp)/'human-scores-status.json').read_text())['status'],'awaiting_articles_and_human_scores')


if __name__=='__main__':unittest.main()

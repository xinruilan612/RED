"""Offline ablations test attribution, N/A handling and source/evidence isolation."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('structure_ablation', APP/'scripts/structure_ablation.py')
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)


class StructureAblationTests(unittest.TestCase):
    def fixture(self):
        material = '示例S1是虚构设备。重量68克。没有亲测记录和比较测试。'
        classification = {'domains':['digital'],'channel':'xiaohongshu','format':'note'}
        own = {'source_id':'own','text':'为什么选择？\n我用了30天，重量68克。\n相比旧款更便宜。',
               'classification':classification}
        foreign = {'source_id':'foreign','text':'我用了21天，价格10元。\n注意限制。',
                   'classification':{'domains':['beauty'],'channel':'xiaohongshu','format':'note'}}
        facts=[];start=0
        for fragment in material.split('。'):
            if not fragment:continue
            offset=material.index(fragment,start);start=offset+len(fragment)
            facts.append({'quote':fragment,'source_id':'fixture', 'start':offset,'end':start,'unit':'unicode_codepoint'})
        task={'id':'fixture','category':'digital','topic':'设备介绍','material':material,
              'input':{'creation':classification},'facts':facts,'reference_example':own,
              'answer':'亲测记录：我使用了30天，有真实记录。'}
        return task,[own,foreign]

    def test_no_structure_is_not_applicable_instead_of_perfect_score(self):
        task,pool=self.fixture()
        row=study.evaluate_task(task,pool)[0]
        self.assertEqual(row['arm'],'A')
        self.assertEqual(row['slot_count'],0)
        self.assertIsNone(row['unsupported_slot_count'])
        self.assertIsNone(row['foreign_source_selected'])
        self.assertIn('not_applicable',row['metric_status'])

    def test_isolation_and_adaptation_are_separate_interventions(self):
        task,pool=self.fixture()
        rows={r['arm']:r for r in study.evaluate_task(task,pool)}
        self.assertEqual(rows['B']['selected_source_id'],'foreign')
        self.assertTrue(rows['B']['foreign_source_selected'])
        self.assertEqual(rows['C']['selected_source_id'],'own')
        self.assertEqual(rows['D']['selected_source_id'],'own')
        self.assertFalse(rows['C']['foreign_source_selected'])
        self.assertEqual(rows['C']['adaptations'],[])
        self.assertGreater(rows['C']['unsupported_slot_count'],0)
        self.assertEqual(rows['D']['unsupported_slot_count'],0)
        self.assertEqual(rows['C']['slot_count'],rows['D']['slot_count'])
        self.assertTrue(rows['D']['adaptations'])
        self.assertEqual(rows['C']['availability'],rows['D']['availability'])
        self.assertEqual(rows['B']['candidate_sources'],rows['D']['candidate_sources'])

    def test_fixed_answer_is_not_used_to_mark_firsthand_available(self):
        task,pool=self.fixture()
        evidence=study.available_evidence(task)
        self.assertIn('product_specs',evidence['fields'])
        self.assertNotIn('firsthand_record',evidence['fields'])
        self.assertNotIn('comparison_specs',evidence['fields'])
        task['answer']='现在声称所有类型证据都有。'
        self.assertEqual(evidence,study.available_evidence(task))

    def test_reproducible_pure_and_no_network(self):
        task,pool=self.fixture();before=copy.deepcopy((task,pool))
        with patch('socket.socket',side_effect=AssertionError('Network forbidden')):
            first=study.evaluate_task(task,pool)
            second=study.evaluate_task(task,list(reversed(pool)))
        self.assertEqual(first,second)
        self.assertEqual((task,pool),before)
        self.assertTrue(all(row['human_macro_f1'] is None and row['human_quality_score'] is None for row in first))

    def test_requires_explicit_foreign_distractor(self):
        task,pool=self.fixture()
        with self.assertRaisesRegex(ValueError,'foreign-domain'):
            study.evaluate_task(task,[pool[0]])

    def test_full_dataset_is_20_tasks_30_sources_and_80_cases(self):
        dataset=APP/'docs/evidence/sprint-20261102/dataset'
        report=study.study(dataset)
        self.assertEqual(report['task_count'],20)
        self.assertEqual(report['structure_source_count'],30)
        self.assertEqual(len(report['cases']),80)
        self.assertEqual(report['paid_calls'],0)
        self.assertFalse(report['human_labels_completed'])
        self.assertIn('刻意',report['disclaimer'])
        self.assertTrue(all(len(case['candidate_sources'])==30 for case in report['cases']))
        for task_id in {row['task_id'] for row in report['cases']}:
            subset=[r for r in report['cases'] if r['task_id']==task_id]
            self.assertTrue(all(row['availability']==subset[0]['availability'] for row in subset))

    def test_task_reference_and_fact_spans_cannot_silently_drift(self):
        task,pool=self.fixture()
        task['reference_example']=copy.deepcopy(task['reference_example'])
        task['reference_example']['text']='Changed source'
        with self.assertRaisesRegex(ValueError,'frozen source pool'):
            study.evaluate_task(task,pool)
        task,pool=self.fixture()
        task['facts'][0]['start']=1
        with self.assertRaisesRegex(ValueError,'Fact span changed'):
            study.evaluate_task(task,pool)

    def test_changed_source_hash_fails_before_any_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            (directory/'20tasks.json').write_text(json.dumps({'items':[]}))
            (directory/'sample.txt').write_text('Changed source')
            (directory/'30structure_samples.json').write_text(json.dumps({'items':[{
                'id':'test','text_path':'sample.txt','text_sha256':'wrong'}]}))
            with self.assertRaisesRegex(ValueError,'fingerprint changed'):
                study.study(directory)


if __name__=='__main__':
    unittest.main()

import json
import copy
from pathlib import Path
import tempfile
import unittest

from scripts.algorithm_bench import build_report, write_report


class AlgorithmBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_report()

    def test_fixed_seed_and_explicit_synthetic_boundary(self):
        def stable(value):
            value = copy.deepcopy(value)
            for task in value['tasks']:
                task['coverage'].pop('solve_ms')
            value['summary']['coverage_diagnostics'].pop('mean_exact_solve_ms')
            value['summary']['coverage_diagnostics'].pop('mean_greedy_solve_ms')
            return value
        self.assertEqual(stable(self.report), stable(build_report()))
        self.assertEqual(self.report['task_count'], 24)
        self.assertEqual(self.report['data_type'], 'constructed_synthetic')
        self.assertEqual(self.report['model_calls'], 0)
        self.assertEqual(self.report['network_requests'], 0)
        self.assertIn('不是实际生成质量', self.report['disclaimer'])

    def test_budget_and_enumeration_bound(self):
        for task in self.report['tasks']:
            coverage = task['coverage']
            for group in ['first_fit', 'greedy', 'enumerated_optimal']:
                value = coverage[group]
                self.assertLessEqual(value['used_budget'], coverage['budget'])
                self.assertNotIn('unsupported', value['selected_ids'])
                self.assertLessEqual(value['coverage_numerator'], value['coverage_denominator'])
                self.assertLessEqual(value['objective'], coverage['enumerated_optimal']['objective'] + 1e-8)
        self.assertTrue(any(f['kind'] == 'greedy_below_enumerated_optimum' for f in self.report['failure_cases']))

    def test_standard_answers_are_the_resolution_denominator(self):
        for task in self.report['tasks']:
            gaps = task['gaps']
            for group in ['in_order', 'ranked']:
                asked = gaps[group]['asked_ids']
                expected = set(block for key in asked for block in gaps['standard_answer_blocks'][key])
                self.assertEqual(expected, set(gaps[group]['resolved_blocks']))
                self.assertLessEqual(len(asked), gaps['question_limit'])
            self.assertEqual(gaps['total_resolvable_blocks'], 7)

    def test_structure_metadata_and_evidence_adaptation(self):
        summary = self.report['summary']['structure']
        self.assertGreater(summary['raw_unsupported_numerator'], 0)
        self.assertEqual(summary['adapted_unsupported_numerator'], 0)
        self.assertEqual(summary['metadata_prose_leaks_numerator'], 0)
        self.assertEqual(summary['metadata_fact_leaks_numerator'], 0)
        self.assertGreater(len({tuple(t['structure']['classification']['domains']) for t in self.report['tasks']}), 1)

    def test_totals_recompute_from_raw_tasks(self):
        for group, summary in self.report['summary']['coverage'].items():
            self.assertEqual(summary['numerator'], sum(t['coverage'][group]['coverage_numerator'] for t in self.report['tasks']))
            self.assertEqual(summary['denominator'], sum(t['coverage'][group]['coverage_denominator'] for t in self.report['tasks']))
        json.dumps(self.report, allow_nan=False)

    def test_exact_and_ablations_have_verifiable_diagnostics(self):
        diagnostics = self.report['summary']['coverage_diagnostics']
        self.assertEqual(diagnostics['exact_objective_gap_vs_reference_sum'], 0)
        self.assertGreater(diagnostics['exact_objective_gain_vs_greedy_sum'], 0)
        self.assertEqual(diagnostics['unsupported_selected_exact'], 0)
        self.assertGreater(diagnostics['unsupported_selected_without_gate'], 0)
        self.assertLessEqual(diagnostics['candidate_recall_numerator'], diagnostics['candidate_recall_denominator'])
        for task in self.report['tasks']:
            coverage = task['coverage']
            self.assertAlmostEqual(coverage['exact']['objective'], coverage['enumerated_optimal']['objective'])
            self.assertGreaterEqual(coverage['solve_ms']['exact'], 0)
            self.assertIn('current admitted candidate pool', coverage['optimality_scope'])

    def test_report_files_and_input_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = write_report(self.report, directory)
            self.assertEqual(json.loads(paths[0].read_text()), self.report)
            text = paths[1].read_text()
            self.assertIn('失败案例', text)
            self.assertIn('没有生成正文', text)
            self.assertIn('synthetic-00', text)
            self.assertEqual(set(p.name for p in Path(directory).iterdir()), {'benchmark.json', 'REPORT.md'})
        for value in [0, 23, 201, True]:
            with self.assertRaises(ValueError):
                build_report(value)


if __name__ == '__main__':
    unittest.main()

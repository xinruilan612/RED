"""Controlled counterexamples, not model-quality or real-user evidence."""
import copy
import json
import unittest

from backend.planning import plan
from backend.gap_ranker import rank_questions


def module(identifier, covers, length=10, **extra):
    return dict(id=identifier, covers=covers, length=length, supported=True, source_ids=['fact-1'], **extra)


class CoveragePlanningTests(unittest.TestCase):
    def setUp(self):
        self.requirements = [dict(id='install', weight=3), dict(id='size', weight=2), dict(id='color', weight=0.1)]

    def test_budget_and_weighted_marginal_selection(self):
        result = plan(self.requirements, [module('appearance', ['color']), module('installation', ['install', 'size']), module('repeat', ['size'])], 20)
        self.assertEqual(result['selected_module_ids'], ['installation', 'appearance'])
        self.assertEqual(result['weighted_coverage'], 1)
        self.assertLessEqual(result['used_budget'], 20)
        self.assertEqual(result['remaining_budget'], 0)
        self.assertTrue(result['optimality_guaranteed'])

    def test_unsupported_claim_cannot_win_even_with_full_coverage(self):
        unsafe = dict(id='fake', covers=['install', 'size'], length=1, supported=False, source_ids=['example-1'])
        missing_source = dict(id='no-source', covers=['install'], length=1, supported=True)
        result = plan(self.requirements, [unsafe, missing_source, module('safe', ['size'])], 20)
        self.assertEqual(result['selected_module_ids'], ['safe'])
        self.assertEqual({i['reason'] for i in result['excluded']}, {'unsupported_assertion'})
        self.assertIn('install', result['uncovered_requirement_ids'])

    def test_question_is_not_counted_as_answered_requirement(self):
        question = dict(id='ask', covers=['install'], length=1, statement_type='question')
        result = plan(self.requirements, [question], 20)
        self.assertEqual(result['covered_weight'], 0)
        self.assertEqual(result['selected_modules'], [])

    def test_unknown_requirement_excluded(self):
        result = plan(self.requirements, [module('unknown', ['made-up'])], 10)
        self.assertEqual(result['excluded'][0]['reason'], 'unknown_requirements')

    def test_selection_log_recomputes_score(self):
        result = plan(self.requirements, [module('one', ['install']), module('two', ['install', 'size'])], 20, solver='greedy')
        for step in result['steps']:
            scores = [c for c in step['candidates'] if c['fits_budget'] and c['marginal_gain'] > 0]
            best = min(scores, key=lambda c: (-c['score'], -c['new_weight'], c['length'], c['id']))
            self.assertEqual(best['id'], step['selected_id'])
            for candidate in scores:
                self.assertAlmostEqual(candidate['score'], (candidate['new_weight'] - 0.15 * candidate['redundant_weight']) / candidate['length'])

    def test_greedy_is_not_claimed_optimal(self):
        requirements = [dict(id='a', weight=3), dict(id='b', weight=2), dict(id='c', weight=2)]
        result = plan(requirements, [module('ratio-trap', ['a'], 3), module('better-total', ['b', 'c'], 5)], 5, solver='greedy')
        self.assertEqual(result['selected_module_ids'], ['ratio-trap'])
        self.assertFalse(result['optimality_guaranteed'])

    def test_deterministic_tie_and_nonmutation(self):
        modules = [module('z', ['size']), module('a', ['size'])]
        before = copy.deepcopy(modules)
        result = plan(self.requirements, modules, 10)
        other = plan(self.requirements, list(reversed(modules)), 10)
        result.pop('elapsed_ms')
        other.pop('elapsed_ms')
        self.assertEqual(result, other)
        self.assertEqual(modules, before)
        json.dumps(result, allow_nan=False)

    def test_empty_zero_and_invalid_input(self):
        self.assertIsNone(plan([], [], 0)['weighted_coverage'])
        self.assertEqual(plan(self.requirements, [module('a', ['size'])], 0)['selected_modules'], [])
        for value in [-1, float('inf'), float('nan'), True, '10']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                plan([], [], value)
        with self.assertRaises(ValueError):
            plan(self.requirements, [module('a', ['size'], 0)], 10)
        with self.assertRaises(ValueError):
            plan([dict(id='x'), dict(id='x')], [], 10)

    def test_exact_beats_greedy_trap_with_same_budget(self):
        requirements = [dict(id='a', weight=3), dict(id='b', weight=2), dict(id='c', weight=2)]
        result = plan(requirements, [module('ratio-trap', ['a'], 3), module('better-total', ['b', 'c'], 5)], 5)
        self.assertEqual(result['selected_module_ids'], ['better-total'])
        self.assertTrue(result['optimality_guaranteed'])
        self.assertFalse(result['global_retrieval_optimality'])
        self.assertEqual(result['objective_value'], 4)
        self.assertEqual(result['greedy_objective'], 3)
        self.assertEqual(result['objective_gap_vs_greedy'], 1)
        self.assertEqual(result['subsets_examined'], 4)
        self.assertGreaterEqual(result['elapsed_ms'], 0)

    def test_twelve_exact_thirteen_greedy_boundary(self):
        for count in (12, 13):
            result = plan(self.requirements, [module('m%02d' % i, ['size']) for i in range(count)], 10)
            self.assertEqual(result['optimality_guaranteed'], count == 12)
            self.assertEqual(result['subsets_examined'], 4096 if count == 12 else 0)
            self.assertEqual(result['candidate_recall_numerator'], 1)
            self.assertEqual(result['candidate_recall_denominator'], 3)

    def test_exact_respects_redundancy_and_uncovered_candidate_gaps(self):
        result = plan(self.requirements, [module('a', ['install']), module('b', ['install']), module('c', ['size'])], 30)
        self.assertEqual(set(result['selected_module_ids']), {'a', 'c'})
        self.assertEqual(result['objective_value'], 5)
        self.assertEqual(result['candidate_recall_numerator'], 2)
        self.assertIn('color', result['uncovered_requirement_ids'])


class GapRankingTests(unittest.TestCase):
    def test_high_impact_question_beats_minor_detail(self):
        gaps = [dict(id='color', question='颜色？', importance=0.2, resolvable=True, blocks=['color']),
                dict(id='version', question='普通版还是上下水版？', importance=1, resolvable=True, blocks=['size', 'installation'])]
        result = rank_questions(gaps, max_questions=1)
        self.assertEqual(result['questions'][0]['id'], 'version')
        self.assertEqual(result['questions'][0]['value'], 1.5)
        self.assertTrue(result['questions'][0]['can_skip'])
        self.assertFalse(result['is_information_entropy'])

    def test_cost_and_unknown_resolvability(self):
        gaps = [dict(id='expensive', question='请提交报告', importance=1, resolvable=True, cost=10),
                dict(id='simple', question='型号是什么', importance=0.8, resolvable=True, cost=0),
                dict(id='unknown', question='未知证据', importance=1)]
        result = rank_questions(gaps)
        self.assertEqual([q['id'] for q in result['questions']], ['simple'])
        self.assertIn(dict(id='unknown', reason='not_resolvable'), result['skipped'])

    def test_deduplicate_question_and_dependent_blocks(self):
        gaps = [dict(id='a', question='型号是什么？', importance=1, resolvable=True, blocks=['size']),
                dict(id='b', question=' 型号是什么! ', importance=1, resolvable=True, blocks=['other']),
                dict(id='c', question='请确认尺寸', importance=1, resolvable=True, blocks=['size'])]
        result = rank_questions(gaps, max_questions=2)
        self.assertEqual([q['id'] for q in result['questions']], ['a'])
        self.assertIn(dict(id='b', reason='duplicate_question'), result['skipped'])
        self.assertIn(dict(id='c', reason='redundant_blocks'), result['skipped'])

    def test_skipped_resolved_empty_and_threshold(self):
        gaps = [dict(id='a', question='a', importance=1, resolvable=True, skipped=True),
                dict(id='b', question='b', importance=1, resolvable=True, resolved=True),
                dict(id='c', question='???', importance=1, resolvable=True),
                dict(id='d', question='d', importance=0.1, resolvable=True)]
        result = rank_questions(gaps)
        self.assertEqual(result['questions'], [])
        self.assertTrue(result['can_continue_without_answers'])
        self.assertEqual({i['reason'] for i in result['skipped']}, {'user_skipped', 'resolved', 'empty_question', 'below_threshold'})

    def test_log_and_purity_and_stability(self):
        gaps = [dict(id='b', question='b', importance=1, resolvable=True), dict(id='a', question='a', importance=1, resolvable=True)]
        before = copy.deepcopy(gaps)
        result = rank_questions(gaps)
        self.assertEqual([q['id'] for q in result['questions']], ['a', 'b'])
        self.assertEqual(result['questions'], rank_questions(list(reversed(gaps)))['questions'])
        self.assertEqual(gaps, before)
        for step in result['steps']:
            best = min(step['candidates'], key=lambda c: (-c['value'], c['id']))
            self.assertEqual(step['selected_id'], best['id'])
        json.dumps(result, allow_nan=False)

    def test_limit_zero_and_invalid_inputs(self):
        self.assertEqual(rank_questions([], max_questions=0)['questions'], [])
        for max_questions in [-1, 11, True, 1.5]:
            with self.subTest(limit=max_questions), self.assertRaises(ValueError):
                rank_questions([], max_questions=max_questions)
        for value in [-1, 1.1, float('nan'), 'high']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                rank_questions([dict(id='x', question='x', importance=value)])


if __name__ == '__main__':
    unittest.main()

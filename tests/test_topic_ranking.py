import copy
import json
import math
import unittest
from datetime import datetime, timedelta, timezone
from backend.topic_ranking import evaluate

BASE = datetime(2020, 1, 1, tzinfo=timezone.utc)

def item(i, vector=None, value=10, image=None):
    return dict(id=str(i), title='题目'+str(i), text_vector=vector if vector is not None else [1., 0.], image_vector=image,
                value=value, published_at=(BASE+timedelta(days=i*3)).isoformat(),
                observed_at=(BASE+timedelta(days=i*3+1)).isoformat())


def candidate(i, vector=None, image=None):
    return dict(id='c'+str(i), title='方向'+str(i), text_vector=vector if vector is not None else [1., 0.], image_vector=image)


class TopicRankingTests(unittest.TestCase):
    def test_cold_start_changes_with_arbitrary_profile(self):
        candidates = [candidate(1, [1, 0]), candidate(2, [0, 1])]
        for profile, expected in [([1, 0], 'c1'), ([0, 1], 'c2')]:
            result = evaluate(profile, candidates, [])
            self.assertEqual(result['candidates'][0]['id'], expected)
            self.assertEqual(result['status'], 'matching_only')
            self.assertTrue(all(r['estimated_value'] is None for r in result['candidates']))
            self.assertEqual(result['candidates'][0]['image_mode'], 'text_only')

    def test_profile_changes_reference_selection_without_domain_rules(self):
        history = [item(0, [1, 0]), item(1, [0, 1])]
        config = dict(profile_weight=1, text_weight=0, image_weight=0, neighbors=1)
        first = evaluate([1, 0], [candidate(0, [1, 1])], history, config)
        second = evaluate([0, 1], [candidate(0, [1, 1])], history, config)
        self.assertEqual(first['candidates'][0]['reference_ids'], ['0'])
        self.assertEqual(second['candidates'][0]['reference_ids'], ['1'])

    def test_image_changes_retrieval_and_missing_image_falls_back(self):
        history = [item(0, image=[1, 0]), item(1, image=[0, 1])]
        config = dict(text_weight=0, profile_weight=0, image_weight=1, neighbors=1)
        a = evaluate([1, 0], [candidate(0, image=[1, 0])], history, config)['candidates'][0]
        b = evaluate([1, 0], [candidate(0, image=[0, 1])], history, config)['candidates'][0]
        self.assertEqual(a['reference_ids'], ['0'])
        self.assertEqual(b['reference_ids'], ['1'])
        self.assertEqual(a['image_mode'], 'multimodal')
        c = evaluate([1, 0], [candidate(0)], history, config)['candidates'][0]
        self.assertEqual(c['image_mode'], 'crossmodal')

    def test_cold_start_image_participates_in_profile_fit(self):
        candidates = [candidate(0, [1, 0], [1, 0]), candidate(1, [1, 0], [0, 1])]
        result = evaluate([0, 1], candidates, [])
        self.assertEqual(result['candidates'][0]['id'], 'c1')
        self.assertGreater(result['candidates'][0]['fit_score'], result['candidates'][1]['fit_score'])
        self.assertGreater(result['candidates'][0]['profile_similarity'], result['candidates'][1]['profile_similarity'])
        self.assertTrue(all(r['image_mode'] == 'crossmodal' for r in result['candidates']))
        self.assertTrue(all(r['estimated_value'] is None for r in result['candidates']))

    def test_candidate_image_retrieves_text_only_history(self):
        history = [item(0, [1, 0]), item(1, [0, 1])]
        config = dict(text_weight=0, image_weight=1, profile_weight=0, neighbors=1)
        result = evaluate([1, 0], [candidate(0, [1, 0], [0, 1])], history, config)['candidates'][0]
        self.assertEqual(result['reference_ids'], ['1'])
        self.assertEqual(result['image_mode'], 'crossmodal')
        self.assertTrue(result['references'][0]['image_used'])
        self.assertEqual(result['references'][0]['image_mode'], 'crossmodal')

    def test_history_image_retrieved_with_candidate_text(self):
        history = [item(0, [1, 0], image=[0, 1]), item(1, [1, 0], image=[1, 0])]
        config = dict(text_weight=0, image_weight=1, profile_weight=0, neighbors=1)
        result = evaluate([1, 0], [candidate(0, [0, 1])], history, config)['candidates'][0]
        self.assertEqual(result['reference_ids'], ['0'])
        self.assertEqual(result['image_mode'], 'crossmodal')

    def test_image_dimension_must_match_shared_text_space(self):
        with self.assertRaises(ValueError):
            evaluate([1, 0], [candidate(0, image=[1, 0, 0])], [])

    def test_missing_metrics_are_references_but_never_training(self):
        history = [item(i, value=None) for i in range(15)]
        history[0]['observed_at'] = None
        result = evaluate([1, 0], [candidate(0)], history)
        self.assertEqual(result['validation']['eligible_count'], 0)
        self.assertEqual(result['validation']['total_count'], 15)
        self.assertEqual(result['validation']['n_backtests'], 0)
        self.assertTrue(result['candidates'][0]['references'])
        self.assertIsNone(result['candidates'][0]['estimated_value'])
        self.assertFalse(result['candidates'][0]['references'][0]['eligible'])

    def test_exact_constant_baseline_does_not_unlock_predictions(self):
        result = evaluate([1, 0], [candidate(0)], [item(i) for i in range(20)])
        self.assertGreaterEqual(result['validation']['n_backtests'], 5)
        self.assertEqual(result['validation']['model_mae'], 0)
        self.assertFalse(result['validation']['gate'])
        self.assertIsNone(result['candidates'][0]['estimated_value'])

    def test_structured_signal_unlocks_experimental_predictions(self):
        history = [item(i, [1, 0] if i % 2 else [0, 1], 100 if i % 2 else 10) for i in range(30)]
        result = evaluate([1, 1], [candidate(0, [1, 0]), candidate(1, [0, 1])], history,
                          dict(text_weight=1, image_weight=0, profile_weight=0, neighbors=3))
        self.assertEqual(result['status'], 'experimental_prediction')
        self.assertLess(result['validation']['model_mae'], result['validation']['baseline_mae'])
        self.assertEqual(result['candidates'][0]['estimated_value'], 100.)
        json.dumps(result, allow_nan=False)

    def test_backtest_never_uses_future_labels_or_current_target(self):
        history = [item(i, [1, 0] if i % 2 else [0, 1], i*10) for i in range(20)]
        history[0]['observed_at'] = (BASE+timedelta(days=100)).isoformat()
        result = evaluate([1, 1], [candidate(0)], history)
        by_id = {r['id']: r for r in history}
        for test in result['validation']['backtests']:
            target = by_id[test['id']]
            for ref_id in test['reference_ids']:
                self.assertNotEqual(ref_id, test['id'])
                self.assertLess(by_id[ref_id]['published_at'], target['published_at'])
                self.assertLessEqual(by_id[ref_id]['observed_at'], target['published_at'])
            self.assertNotIn('0', test['reference_ids'])

    def test_past_ablation_removes_harmful_reference(self):
        history = [item(i, value=100 if i == 0 else 10) for i in range(20)]
        result = evaluate([1, 0], [candidate(0)], history)
        backtests = result['validation']['backtests']
        self.assertIn('0', backtests[0]['reference_ids'])
        self.assertNotIn('0', backtests[1]['reference_ids'])
        self.assertNotIn('0', result['candidates'][0]['reference_ids'])

    def test_delayed_ablation_cannot_change_earlier_reference_selection(self):
        history = [item(i, value=100 if i == 0 else 10) for i in range(20)]
        history[5]['observed_at'] = (BASE+timedelta(days=100)).isoformat()
        changed = copy.deepcopy(history)
        changed[5]['value'] = 100000
        first = evaluate([1, 0], [candidate(0)], history)['validation']['backtests']
        second = evaluate([1, 0], [candidate(0)], changed)['validation']['backtests']
        self.assertEqual([r['reference_ids'] for r in first], [r['reference_ids'] for r in second])
        self.assertIn('0', next(r for r in first if r['id'] == '6')['reference_ids'])

    def test_future_rows_excluded_and_arguments_not_mutated(self):
        history = [item(0)]
        history[0]['observed_at'] = '2999-01-01T00:00:00+00:00'
        before = copy.deepcopy(history)
        result = evaluate([1, 0], [candidate(0)], history)
        self.assertEqual(history, before)
        self.assertEqual(result['validation']['excluded_future_count'], 1)
        self.assertEqual(result['candidates'][0]['reference_ids'], [])

    def test_invalid_vectors_weights_ids_dates_rejected(self):
        bad_vectors = [[0, 0], [float('nan'), 0], [float('inf'), 1], [True, 0], [], [1]]
        for vector in bad_vectors:
            with self.subTest(vector=vector), self.assertRaises(ValueError):
                evaluate([1, 0], [candidate(0, vector)], [])
        for config in [dict(text_weight=-1), dict(neighbors=0), dict(neighbors=True), dict(image_weight=math.inf), dict(text_weight=0, image_weight=0, profile_weight=0)]:
            with self.subTest(config=config), self.assertRaises(ValueError):
                evaluate([1, 0], [candidate(0)], [], config)
        with self.assertRaises(ValueError):
            evaluate([1, 0], [candidate(0), candidate(0)], [])
        h = item(0)
        h['published_at'] = '2020-01-01'
        with self.assertRaises(ValueError):
            evaluate([1, 0], [candidate(0)], [h])
        with self.assertRaises(ValueError):
            evaluate([1, 0], [candidate(0, image=[1, 0])], [item(0, image=[1, 0, 0])])

    def test_large_finite_vectors_normalize_without_nan(self):
        result = evaluate([1e308, 1e308], [candidate(0, [1e308, 1e308])], [])
        self.assertEqual(result['candidates'][0]['fit_score'], 100.)
        json.dumps(result, allow_nan=False)


if __name__ == '__main__':
    unittest.main()

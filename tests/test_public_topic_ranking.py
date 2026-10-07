import copy
import unittest

from backend.public_topic_ranking import rank_public


class PublicRankingTests(unittest.TestCase):
    def setUp(self):
        self.candidates = [{'id': 'candidate', 'text_vector': [1, 0]}]
        self.samples = [dict(id='a', title='摄影', url='https://example.com/a',
                             collected_at='2026-01-01T00:00:00Z', text_vector=[1, 0], likes=12),
                        dict(id='b', title='做饭', url='https://example.com/b',
                             collected_at='2026-01-01T00:00:00Z', text_vector=[0, 1], likes=90000)]

    def run_rank(self, profile=None, **config):
        return rank_public(profile or [1, 0], self.candidates, self.samples, config)

    def test_relevance_not_popularity_and_no_prediction(self):
        result = self.run_rank()
        self.assertEqual(result['candidates'][0]['public_references'][0]['id'], 'a')
        self.assertFalse(result['prediction_available'])
        self.assertNotIn('estimated_value', str(result))

    def test_profile_changes_reference_selection(self):
        a = self.run_rank(profile_weight=1, text_weight=0, image_weight=0)
        b = self.run_rank([0, 1], profile_weight=1, text_weight=0, image_weight=0)
        self.assertEqual(a['candidates'][0]['public_references'][0]['id'], 'a')
        self.assertEqual(b['candidates'][0]['public_references'][0]['id'], 'b')

    def test_real_image_changes_order(self):
        self.candidates[0]['image_vector'] = [0, 1]
        self.samples[0]['image_vector'] = [1, 0]
        self.samples[1]['image_vector'] = [0, 1]
        refs = self.run_rank(image_weight=1, text_weight=0, profile_weight=0)['candidates'][0]['public_references']
        self.assertEqual(refs[0]['id'], 'b')
        self.assertEqual(refs[0]['image_mode'], 'multimodal')
        self.assertFalse(refs[0]['image_missing'])

    def test_crossmodal_does_not_claim_reference_image(self):
        self.candidates[0]['image_vector'] = [1, 0]
        ref = self.run_rank()['candidates'][0]['public_references'][0]
        self.assertEqual(ref['image_mode'], 'crossmodal')
        self.assertTrue(ref['image_missing'])
        self.assertIn('未参与', ref['image_note'])

    def test_missing_counts_not_zero_and_sources_retained(self):
        ref = self.run_rank()['candidates'][0]['public_references'][0]
        self.assertIsNone(ref['saves'])
        self.assertEqual(ref['url'], self.samples[0]['url'])
        self.assertEqual(ref['collected_at'], self.samples[0]['collected_at'])
        self.assertEqual(ref['metric_semantics'], 'cumulative_at_collection')

    def test_empty_samples_and_no_input_mutation(self):
        before = copy.deepcopy(self.samples)
        self.run_rank()
        self.assertEqual(before, self.samples)
        result = rank_public([1, 0], self.candidates, [])
        self.assertEqual(result['public_sample_count'], 0)
        self.assertEqual(result['candidates'][0]['public_references'], [])

    def test_backend_snapshot_contract(self):
        self.samples[0]['observed_at'] = self.samples[0].pop('collected_at')
        self.samples[0]['counts'] = {'likes': 18, 'saves': None, 'comments': 0}
        ref = self.run_rank()['candidates'][0]['public_references'][0]
        self.assertEqual(ref['likes'], 18)
        self.assertEqual(ref['comments'], 0)
        self.assertIsNone(ref['saves'])
        self.assertEqual(ref['collected_at'], self.samples[0]['observed_at'])

    def test_future_sample_excluded(self):
        self.samples[0]['collected_at'] = '2999-01-01T00:00:00Z'
        result = self.run_rank()
        self.assertEqual(result['excluded_future_count'], 1)

    def test_duplicate_and_invalid_vectors_rejected(self):
        self.samples.append(dict(self.samples[0]))
        with self.assertRaises(ValueError):
            self.run_rank()
        self.samples.pop()
        self.samples[0]['text_vector'] = [1, 0, 0]
        with self.assertRaises(ValueError):
            self.run_rank()

    def test_invalid_counts_sources_and_times_rejected(self):
        for key, value in [('likes', -1), ('saves', float('nan')), ('comments', True),
                           ('url', 'javascript:alert(1)'), ('url', 'https://user:secret@example.com'),
                           ('collected_at', '2026-01-01'), ('published_at', '2027-01-01T00:00:00Z')]:
            with self.subTest(key=key, value=value):
                before = copy.deepcopy(self.samples[0])
                self.samples[0][key] = value
                with self.assertRaises(ValueError):
                    self.run_rank()
                self.samples[0] = before

    def test_invalid_config_rejected(self):
        for config in [dict(neighbors=True), dict(neighbors=30), dict(text_weight=float('nan')),
                       dict(text_weight=0, image_weight=0, profile_weight=0)]:
            with self.subTest(config=config), self.assertRaises(ValueError):
                self.run_rank(**config)


if __name__ == '__main__':
    unittest.main()

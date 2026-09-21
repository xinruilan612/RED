import unittest
from uuid import uuid4

import test_operations
from backend.contracts import DomainError
from backend.demo import validate_brief
from backend.experiments import ALGORITHM, recommend


class ExperimentDecisionTests(unittest.TestCase):
    setUp = test_operations.OperationsTests.setUp
    tearDown = test_operations.OperationsTests.tearDown
    command = test_operations.OperationsTests.command

    def sample(self):
        state = self.command('load_sample', {})
        self.account = state['accounts'][-1]
        return state

    def test_untested_pillar_is_explored_and_decision_is_explainable(self):
        state = self.sample()
        state = self.command('recommend_experiment', {
            'account_id': self.account['id'], 'source_type': 'simulation', 'window': '24h'})
        decision = state['experiments'][0]
        self.assertEqual(decision['algorithm'], ALGORITHM)
        self.assertEqual(decision['decision_mode'], 'explore')
        self.assertEqual(decision['chosen_pillar'], '衣橱整理')
        self.assertEqual(decision['sample_size'], 4)
        self.assertEqual(len(decision['metric_refs']), 4)
        self.assertIn('收藏×3', decision['reward_formula'])
        chosen = next(row for row in decision['candidates'] if row['pillar'] == '衣橱整理')
        self.assertEqual(chosen['samples'], 0)
        self.assertIsNone(chosen['ucb_score'])

    def test_accept_scopes_experiment_and_metric_correction_invalidates_it(self):
        state = self.sample()
        decision = self.command('recommend_experiment', {
            'account_id': self.account['id'], 'source_type': 'simulation', 'window': '24h'})['experiments'][0]
        self.command('experiment_status', {'id': decision['id'], 'status': 'accepted'})
        context = self.ops.context(self.owner, {
            'account_id': self.account['id'], 'platform': 'xiaohongshu', 'experiment_id': decision['id']}, 'simulation')
        self.assertEqual(context['experiment']['id'], decision['id'])
        brief = validate_brief({'topic': '衣橱整理实验', 'audience': '学生', 'tone': '真实'})
        brief.update(mode='simulation', operations=context)
        run = self.store.create(self.owner, str(uuid4()), brief)
        for _ in range(6):
            run = self.store.command(run.run_id, self.owner, run.status_version, str(uuid4()), 'demo_step')
            strategy = next((a['value'] for a in run.artifacts if a['stage'] == 'strategy'), None)
            if strategy: break
        self.assertIn(decision['id'], strategy['learning_refs'])
        self.assertIn(decision['hypothesis'], strategy['next_experiments'])
        with self.assertRaises(DomainError):
            self.ops.context('bob', {'experiment_id': decision['id']}, 'simulation')
        metric = state['metrics'][0]
        post = next(row for row in state['publications'] if row['id'] == metric['publication_id'])
        corrected = {**metric['values'], 'saves': metric['values']['saves'] + 1}
        state = self.command('metrics', {'id': post['id'], 'window': '24h',
            'observed_at': metric['observed_at'], **corrected})
        self.assertEqual(state['experiments'][0]['status'], 'superseded')
        with self.assertRaises(DomainError):
            self.ops.context(self.owner, {'account_id': self.account['id'],
                'platform': 'xiaohongshu', 'experiment_id': decision['id']}, 'simulation')

    def test_ucb_scores_are_deterministic_and_do_not_claim_prediction(self):
        state = self.sample()
        state['accounts'][-1]['profile']['pillars'] = '栏目甲, 栏目乙'
        for index, post in enumerate(state['publications']):
            post['pillar'] = '栏目甲' if index < 2 else '栏目乙'
        first = recommend(state, self.account['id'], 'simulation', '24h', '2026-01-01T00:00:00+00:00')
        second = recommend(state, self.account['id'], 'simulation', '24h', '2026-01-01T00:00:00+00:00')
        for field in ('chosen_pillar', 'decision_mode', 'confidence', 'candidates', 'metric_refs'):
            self.assertEqual(first[field], second[field])
        self.assertTrue(all(row['samples'] == 2 for row in first['candidates']))
        self.assertTrue(any('不预测爆款' in text for text in first['limitations']))

    def test_invalid_source_window_and_status_transitions_are_rejected(self):
        self.sample()
        for payload in ({'account_id': self.account['id'], 'source_type': 'live', 'window': '24h'},
                        {'account_id': self.account['id'], 'source_type': 'simulation', 'window': '1h'}):
            with self.assertRaises(DomainError): self.command('recommend_experiment', payload)
        decision = self.command('recommend_experiment', {
            'account_id': self.account['id'], 'source_type': 'simulation', 'window': '24h'})['experiments'][0]
        self.command('experiment_status', {'id': decision['id'], 'status': 'rejected'})
        with self.assertRaises(DomainError):
            self.command('experiment_status', {'id': decision['id'], 'status': 'accepted'})


if __name__ == '__main__': unittest.main()

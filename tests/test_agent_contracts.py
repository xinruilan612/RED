"""Validate design examples and cross-document contracts, not a running agent system."""
import importlib.util
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
C = json.loads((ROOT/'docs/design/design_contract.json').read_text(encoding='utf-8'))
CARDS = sorted((ROOT/'docs/agents').glob('0[1-4]*.md'))

class AgentContractTests(unittest.TestCase):
    def test_generated_merge_and_registry_are_current(self):
        spec = importlib.util.spec_from_file_location('sync_cards', ROOT/'scripts/sync_agent_cards.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for path, expected in module.outputs().items():
            self.assertEqual(path.read_text(encoding='utf-8'), expected, str(path))

    def test_role_examples_and_privileges_match_contract(self):
        self.assertEqual(len(CARDS), 4)
        for role, path in zip(C['agents'], CARDS):
            text = path.read_text(encoding='utf-8')
            self.assertIn(f'**Agent ID**：`{role}`', text)
            example = json.loads(re.search(r'```json\n(.*?)\n```', text, re.S).group(1))
            self.assertEqual(example['agent_id'], role)
            self.assertEqual(example['schema_version'], C['agent_schema_version'])
            self.assertGreater(example['version'], 0)
            self.assertTrue(all(re.fullmatch(r'[^@]+@[1-9]\d*', ref) for ref in example['input_refs']))
            section = text.split('## 5. 允许的 Tools')[1].split('## 6.')[0]
            tools = re.findall(r'^\| `([^`]+)`', section, re.M)
            self.assertEqual(tools, C['tool_permissions'][role])
            skills = text.split('## 6. 允许的 Skills')[1].split('## 7.')[0]
            self.assertEqual(re.findall(r'^- `([^`]+)`', skills, re.M), C['skill_permissions'][role])

    def test_review_gate_has_no_score_escape(self):
        policy = C['review_policy']
        self.assertEqual(len(policy['checks']), 8)
        self.assertEqual(len(set(policy['checks'])), 8)
        self.assertEqual(set(policy['checks']), set(policy['required_pass']) | set(policy['optional_unknown']))
        self.assertEqual(policy['optional_unknown'], ['originality_risk'])
        self.assertEqual(set(policy['blocking_severities']), {'blocker', 'major'})
        self.assertFalse(policy['score_gate'])
        self.assertNotIn('review_threshold', C['parameters'])
        text = CARDS[3].read_text(encoding='utf-8')
        example = json.loads(re.search(r'```json\n(.*?)\n```', text, re.S).group(1))
        self.assertCountEqual([x['name'] for x in example['checks']], policy['checks'])
        self.assertEqual(example['decision'], 'revision_required')
        self.assertEqual(example['next_action'], 'revise')
        self.assertTrue(any(i['severity'] in policy['blocking_severities'] and i['state']=='open' for i in example['issues']))

    def test_research_example_does_not_authorize_unsupported_claims(self):
        example = json.loads(re.search(r'```json\n(.*?)\n```', CARDS[1].read_text(encoding='utf-8'), re.S).group(1))
        for claim in example['claims']:
            if claim['support_status'] in ('unverified', 'contradicted'):
                self.assertFalse(claim['usable'])
                self.assertIsNone(claim['allowed_wording'])
                self.assertIn(claim['claim_id'], example['prohibited_claims'])

    def test_content_example_has_full_public_text_surface(self):
        text = CARDS[2].read_text(encoding='utf-8')
        ex = json.loads(re.search(r'```json\n(.*?)\n```', text, re.S).group(1))
        self.assertGreaterEqual(len(ex['title_candidates']), C['parameters']['title_candidate_min'])
        self.assertIn(ex['selected_title'], ex['title_candidates'])
        for field in ['selected_title','hook','body','cta','tags','cover_text']:
            self.assertIn(field, ex)
        self.assertIn('strategy → outline → hook → title → body', text)

    def test_budget_and_capability_defaults_are_bounded(self):
        p = C['parameters']
        self.assertLessEqual(p['model_timeout_s'], p['agent_attempt_timeout_s'])
        self.assertLess(p['agent_attempt_timeout_s'], p['run_active_timeout_s'])
        self.assertEqual(p['supplement_rounds_max'], 1)
        self.assertEqual(p['revision_rounds_max'], 2)
        self.assertLessEqual(p['title_candidate_min'], p['title_candidate_count'])
        self.assertEqual(set(C['disabled_tools_default']), {'search_public_sources','fetch_source_text'})
        self.assertTrue(set(C['disabled_tools_default']) <= set(C['tool_permissions']['research']))
        self.assertFalse(p['paid_provider_enabled'])
        self.assertIsNone(p['run_currency_budget'])

    def test_memory_domains_and_events_are_unambiguous(self):
        self.assertEqual(set(C['memory_domains'].values()), {'Profile','Material','History','Profile/History'})
        self.assertNotIn('run_memory', C['memory_domains'])
        self.assertEqual(len(C['events']), len(set(C['events'])))
        self.assertIn('artifact.created', C['events'])
        self.assertNotIn('artifact.saved', C['events'])
        for reason in ['hypothesis_permission','missing_material','budget_exhausted','final_confirmation']:
            self.assertIn(reason, C['wait_reasons'])

if __name__ == '__main__':
    unittest.main()

class OperationsContractTests(unittest.TestCase):
    def test_analytics_extension_is_separate_from_creation_and_matches_runtime(self):
        from backend.analytics import AnalyticsAgent, WINDOW_HOURS
        extension=C['operations_extension']
        self.assertEqual(extension['agents'],[AnalyticsAgent.agent_id])
        self.assertEqual(extension['schema_version'],4)
        self.assertTrue(extension['promotion_policy']['public_fields_explicit'])
        self.assertTrue(extension['promotion_policy']['manual_and_simulation_separated'])
        self.assertEqual(extension['promotion_policy']['inquiry_attribution'],['explicit','multi_touch','unknown'])
        self.assertEqual(extension['windows_hours'],WINDOW_HOURS)
        self.assertEqual(extension['engine'],'deterministic_rules_plus_explainable_ucb1')
        self.assertFalse(extension['experiment_policy']['predicts_virality'])
        self.assertNotIn('analytics',C['join_requires'])
        self.assertEqual(extension['account_key'],'account_id')

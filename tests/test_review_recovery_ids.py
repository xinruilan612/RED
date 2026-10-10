"""Offline replay of a settled synthetic response; never infer approval."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from backend.review_recovery import candidate
from backend.workflow import digest


class RecoveryIdTests(unittest.TestCase):
    def test_real_response_keeps_six_valid_ids_and_requires_reaudit(self):
        path = Path(__file__).parent/'fixtures/review_recovery_real_quote.json'
        original = path.read_bytes(); fixture = json.loads(original)
        content = fixture['content']; draft = {'ref': 'synthetic-draft@1', 'content': content, 'content_hash': digest(content), 'snapshot_id':'offline-snapshot'}
        prior = copy.deepcopy(fixture['prior_review'])
        run = SimpleNamespace(workflow_type='creation', context={'mode':'live','material':fixture['material']},
            run_status='RUNNING', current_stage='reviewer', drafts=[draft], review=None,
            branches={'research':{'data':{'core_gap':False}}}, run_id='offline-replay', snapshot_id='offline-snapshot', prior_review=prior, reviews=[prior],
            events=[{'type':'artifact.created','occurred_at':'2026-10-10T00:00:00+00:00',
                     'payload':{'artifact_ref':draft['ref']}}])
        class ReadOnlyFixtureDB:
            def execute(self, query, params):
                if 'runtime_jobs' in query: value = ('blocked',)
                elif 'live_steps' in query: value = None
                elif 'live_calls' in query:
                    value = (fixture['call_id'],'invalid',json.dumps(fixture['raw'],ensure_ascii=False),
                             fixture['actual_tokens'],run.snapshot_id,1791590401.)
                else: raise AssertionError('Unexpected query')
                return SimpleNamespace(fetchone=lambda: value)
        call_id, report, removed, excluded = candidate(ReadOnlyFixtureDB(),SimpleNamespace(order_column='rowid'),run)
        self.assertEqual(call_id,fixture['call_id'])
        self.assertEqual(len(removed),1)
        self.assertEqual(removed[0]['quote'],'工具完全离线，不需要账号。')
        self.assertEqual(len(report['claim_map']),6)
        self.assertTrue(all(x['excerpt'] in '\n'.join([content['selected_title'],content['body'],content['cta']]+content['tags']) for x in report['claim_map']))
        self.assertEqual(report['decision'],'revision_required')
        self.assertEqual(report['next_action'],'revise')
        self.assertEqual(next(x for x in report['checks'] if x['name']=='evidence_integrity')['result'],'fail')
        self.assertEqual(fixture['raw']['decision'],'approved')
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual(run.review,None)

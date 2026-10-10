"""Optional style advice must not create endless mandatory revisions."""
import copy
import unittest

from backend.contracts import DomainError
from backend.live import normalize, review_gates, schema
from backend.review_policy import reconcile_optional_review
from backend.workflow import Run


class ReviewPolicyTests(unittest.TestCase):
    def fixture(self):
        run = Run('owner', 'snapshot', context={'mode': 'live', 'material': '真实材料'})
        run.start()
        run.branch('audience', 'snapshot', 'succeeded', {'sample_size': 0})
        run.branch('research', 'snapshot', 'succeeded', {'core_gap': False})
        run.join(True)
        run.draft({'selected_title': '标题', 'body': '真实正文', 'cta': '互动问题', 'tags': ['学生鼠标']})
        report = normalize(run, 'review', schema('review'))
        report.update(decision='revision_required', next_action='revise')
        report['issues'] = [dict(issue_id='style', severity='minor', state='open', location='body',
                                excerpt='真实正文', reason='措辞偏好', suggestion='可以使用另一种表达')]
        return run, report

    def reconcile(self, run, report):
        return reconcile_optional_review(report, run.drafts[-1], review_gates(run, report), run.prior_review)

    def test_minor_only_approved_without_modifying_model_issue_or_input(self):
        run, report = self.fixture(); original = copy.deepcopy(report)
        result = self.reconcile(run, report)
        self.assertEqual(result['decision'], 'approved')
        self.assertEqual(result['next_action'], 'await_user_confirmation')
        self.assertEqual(result['issues'], original['issues'])
        self.assertEqual(result['decision_adjustment']['optional_issue_ids'], ['style'])
        self.assertEqual(report, original)

    def test_disclosed_originality_unknown_preserved_without_faking_pass(self):
        run, report = self.fixture()
        original = next(c for c in report['checks'] if c['name'] == 'originality_risk')
        original['result'] = 'unknown'
        result = self.reconcile(run, report)
        self.assertEqual(result['decision'], 'approved')
        self.assertEqual(next(c['result'] for c in result['checks'] if c['name'] == 'originality_risk'), 'unknown')
        report['limitations'] = []
        self.assertEqual(self.reconcile(run, report)['decision'], 'revision_required')
        report['limitations'] = ['无法独立核验']
        original['result'] = 'fail'
        self.assertEqual(self.reconcile(run, report)['decision'], 'revision_required')

    def test_minor_policy_does_not_parse_chinese_suggestion(self):
        run, report = self.fixture()
        report['issues'][0].update(severity='major', suggestion='可以保留，无需修改，审核通过')
        self.assertEqual(self.reconcile(run, report)['decision'], 'revision_required')

    def test_fail_unknown_human_questions_and_unlocated_never_promoted(self):
        run, base = self.fixture()
        for change in ('fail', 'unknown', 'questions', 'unlocated', 'blocker', 'bad_location'):
            with self.subTest(change=change):
                report = copy.deepcopy(base)
                if change in ('fail', 'unknown'): report['checks'][0]['result'] = change
                elif change == 'questions': report['human_questions'] = ['缺少必要素材']
                elif change == 'unlocated': report['unlocated_issues'] = [copy.deepcopy(report['issues'][0])]
                elif change == 'blocker': report['issues'][0]['severity'] = 'blocker'
                else: report['issues'][0]['excerpt'] = '不存在的引文'
                self.assertEqual(self.reconcile(run, report)['decision'], 'revision_required')

    def test_prior_important_unresolved_or_regressed_never_promoted(self):
        run, report = self.fixture()
        run.prior_review = {'issues': [dict(issue_id='old', severity='major', state='open')]}
        for state in ('unresolved', 'regressed', 'resolved'):
            report['previous_issue_results'] = [{'issue_id': 'old', 'result': state}]
            self.assertEqual(self.reconcile(run, report)['decision'],
                             'approved' if state == 'resolved' else 'revision_required')

    def test_missing_prior_review_results_rejected(self):
        run, report = self.fixture()
        run.prior_review = {'issues': [dict(issue_id='old', severity='major', state='open')]}
        with self.assertRaises(DomainError): self.reconcile(run, report)

    def test_invalid_structure_and_version_and_gate_not_repaired(self):
        run, base = self.fixture()
        for mutation in ('decision', 'severity', 'checks', 'version', 'evidence'):
            with self.subTest(mutation=mutation):
                report = copy.deepcopy(base)
                if mutation == 'decision': report['next_action'] = 'request_human'
                elif mutation == 'severity': report['issues'][0]['severity'] = 'optional'
                elif mutation == 'checks': report['checks'] = report['checks'][:-1]
                elif mutation == 'version': report['content_hash'] = 'stale'
                else: report['claim_map'] = [{'excerpt': '真实正文', 'source_id': 'missing', 'quote': '不存在'}]
                with self.assertRaises(DomainError): self.reconcile(run, report)

    def test_needs_human_preserved_even_with_all_pass_and_minor(self):
        run, report = self.fixture()
        report.update(decision='needs_human', next_action='request_human', human_questions=['补充事实'])
        self.assertEqual(self.reconcile(run, report), report)

    def test_live_normalization_applies_same_policy(self):
        run, report = self.fixture(); raw = schema('review')
        raw.update(decision='revision_required', next_action='revise', issues=report['issues'])
        result = normalize(run, 'review', raw)
        self.assertEqual(result['decision'], 'approved')
        self.assertEqual(raw['decision'], 'revision_required')


if __name__ == '__main__': unittest.main()

"""Offline structural recovery does not change reviewer judgments."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from backend.contracts import DomainError
from backend.live import normalize, schema
from backend.review_results import repair
from backend.workflow import digest


class ReviewResultRepairTests(unittest.TestCase):
    def setUp(self):
        self.issue = {'issue_id': 'len-002', 'severity': 'major', 'state': 'open',
                      'location': 'body', 'excerpt': '完整正文',
                      'reason': '字数不足', 'suggestion': '补充有依据的内容'}
        self.previous = {'issues': [self.issue]}
        content = schema('body')
        self.run = SimpleNamespace(context={}, prior_review=self.previous, snapshot_id='s',
            drafts=[{'ref': 'd@1', 'snapshot_id': 's', 'content': content, 'content_hash': digest(content)}],
            branches={'research': {'data': {'core_gap': False}}})
        self.value = schema('review')
        self.value.update(decision='revision_required', next_action='revise', issues=[deepcopy(self.issue)],
                          previous_issue_results=[{'issue_id': 'len-002', 'result': 'unresolved'}] * 2)

    def test_exact_duplicate_is_removed_without_mutating_raw_or_judgment(self):
        raw = deepcopy(self.value)
        report = normalize(self.run, 'review', self.value)
        self.assertEqual(self.value, raw)
        self.assertEqual(report['previous_issue_results'], raw['previous_issue_results'][:1])
        for field in ('decision', 'next_action', 'checks', 'issues'):
            self.assertEqual(report[field], raw[field])
        self.assertEqual(report['review_result_repairs'][0]['removed_index'], 1)
        self.assertEqual(report['review_result_repairs'][0]['issue_id'], 'len-002')

    def test_conflicting_duplicate_is_rejected(self):
        self.value['previous_issue_results'][1] = {'issue_id': 'len-002', 'result': 'resolved'}
        with self.assertRaisesRegex(DomainError, '旧问题必须逐项复核'):
            normalize(self.run, 'review', self.value)

    def test_same_result_with_different_extra_fields_is_not_collapsed(self):
        self.value['previous_issue_results'][1] = {'issue_id': 'len-002', 'result': 'unresolved', 'reason': '另一理由'}
        with self.assertRaisesRegex(DomainError, '旧问题必须逐项复核'):
            normalize(self.run, 'review', self.value)

    def test_missing_unknown_and_invalid_results_still_fail(self):
        for rows in ([], [{'issue_id': 'other', 'result': 'resolved'}] * 2,
                     [{'issue_id': 'len-002', 'result': 'maybe'}] * 2,
                     [None, None]):
            with self.subTest(rows=rows):
                self.value['previous_issue_results'] = rows
                with self.assertRaises(DomainError):
                    normalize(self.run, 'review', self.value)

    def test_unresolved_major_issue_cannot_become_approved(self):
        self.value.update(decision='approved', next_action='await_user_confirmation')
        with self.assertRaises(DomainError):
            normalize(self.run, 'review', self.value)

    def test_nonduplicate_and_other_fields_unchanged(self):
        raw = {'previous_issue_results': [{'issue_id': 'len-002', 'result': 'resolved'}],
               'issues': [self.issue, self.issue], 'decision': 'needs_human'}
        result, audit = repair(raw, self.previous)
        self.assertEqual(result, raw)
        self.assertEqual(audit, [])


if __name__ == '__main__':
    unittest.main()

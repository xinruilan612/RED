import unittest
from scripts.build_original_creation_report import sanitize, matched_review


class OriginalCreationReportTests(unittest.TestCase):
    def test_nested_ownership_and_credentials_are_redacted_without_losing_evidence(self):
        source = {'filters': [{'owner': 'private-owner', 'account_id': 'private-account', 'domains': ['beauty']}],
                  'connection_id': 'private-connection', 'cookie': 'secret', 'source_id': 'kb:evidence'}
        result = sanitize(source)
        self.assertNotIn('private-', str(result))
        self.assertNotIn('secret', str(result))
        self.assertEqual(result['source_id'], 'kb:evidence')
        self.assertEqual(result['filters'][0]['domains'], ['beauty'])
        self.assertEqual(source['cookie'], 'secret')

    def test_stale_review_cannot_approve_current_draft(self):
        draft = {'ref': 'new@1', 'snapshot_id': 'snapshot-new'}
        old = {'draft_ref': 'old@1', 'snapshot_id': 'snapshot-new', 'decision': 'approved'}
        wrong = {'draft_ref': 'new@1', 'snapshot_id': 'snapshot-old', 'decision': 'approved'}
        self.assertIsNone(matched_review({'review': wrong, 'prior_review': old}, draft))
        valid = {'draft_ref': 'new@1', 'snapshot_id': 'snapshot-new', 'decision': 'revision_required'}
        self.assertEqual(matched_review({'review': valid, 'prior_review': old}, draft), valid)


if __name__ == '__main__':
    unittest.main()

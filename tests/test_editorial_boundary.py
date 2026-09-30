"""Reader-copy diagnostics preserve evidence, uncertainty and manual choice."""
import copy
import unittest
from backend.editorial_boundary import findings
from backend.live import normalize, schema, review_gates
from backend.workflow import Run


class EditorialBoundaryTests(unittest.TestCase):
    def run_value(self, body):
        run=Run('owner','snapshot',run_status='RUNNING',current_stage='content',context={'mode':'live'},
                branches={'research':{'data':{'core_gap':False}}})
        run.draft({'selected_title':'标题','body':body,'cta':'你怎么看？','tags':[]})
        return run

    def test_process_notes_are_not_approved_or_silently_deleted(self):
        body='素材里没有更细的权威顺序依据，我先不下定论。后续找到可标注来源，再补一版拆解。'
        run=self.run_value(body);raw=schema('review');original=copy.deepcopy(raw)
        report=normalize(run,'review',raw)
        self.assertEqual(report['decision'],'needs_human')
        self.assertTrue(report['human_questions'])
        self.assertTrue(all(i['state']=='open' for i in report['issues']))
        self.assertEqual(raw['decision'],original['decision'])
        self.assertEqual(run.drafts[-1]['content']['body'],body)
        run.reviewed(report,review_gates(run,report))
        self.assertEqual(run.wait_reason,'missing_material')
        self.assertTrue(run.can_manual_adopt())

    def test_reader_relevant_uncertainty_and_real_attribution_remain_valid(self):
        body='不同肤质的适用情况可能不同，请按产品说明使用。根据产品包装说明，每次只需少量。'
        self.assertEqual(findings({'body':body}),[])
        run=self.run_value(body)
        self.assertEqual(normalize(run,'review',schema('review'))['decision'],'approved')

    def test_internal_metadata_is_detected_in_title_body_and_cta(self):
        content={'selected_title':'已读公开网页的整理','body':'该网页发布时间为空。','cta':'后续找到可标注来源，再补一版拆解。'}
        self.assertEqual({i['location'] for i in findings(content)},{'selected_title','body','cta'})

    def test_repeated_process_note_cannot_be_marked_resolved(self):
        run=self.run_value('网页发布时间为空。')
        first=normalize(run,'review',schema('review'))
        run.prior_review=first
        raw=schema('review')
        raw['previous_issue_results']=[{'issue_id':i['issue_id'],'result':'resolved'} for i in first['issues']]
        report=normalize(run,'review',raw)
        self.assertEqual(report['previous_issue_results'][0]['result'],'unresolved')
        self.assertEqual(raw['previous_issue_results'][0]['result'],'resolved')

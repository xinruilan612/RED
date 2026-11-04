"""All four roles receive the same versioned case evidence and usage boundary."""
import unittest
from types import SimpleNamespace
from backend.live import messages_for

class CasePromptEvidenceTests(unittest.TestCase):
    def test_all_roles_preserve_case_scope_without_exposing_embedding(self):
        source={'source_id':'case-v2-1','source_type':'research_case','text':'第三方使用体验',
                'document_id':'case','version':2,'evidence_role':'expression_reference',
                'content_kind':'text','source_scope':'owned_account',
                'case_ref':{'document_id':'case','version':2},'embedding':[0.1]*512}
        run=SimpleNamespace(context={'topic':'防晒选择','audience':'通勤用户','tone':'理性',
                 'allow_hypothesis':False,'evidence':[source]},branches={},artifacts=[],
                 drafts=[{'content':{'body':'待核实草稿'}}],prior_review=None,review=None)
        for stage in ('audience','research','strategy','body','review'):
            with self.subTest(stage=stage):
                messages,data=messages_for(run,stage)
                material=data['materials'][0]
                self.assertEqual(material['case_ref'],source['case_ref'])
                self.assertEqual(material['evidence_role'],'expression_reference')
                self.assertEqual(material['text'],source['text'])
                self.assertNotIn('embedding',material)
                self.assertIn('不能把案例中的产品功效',messages[0]['content'])

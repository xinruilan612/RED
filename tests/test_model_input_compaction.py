"""Metadata projection saves budget without changing any selected source text."""
import copy
import json
import unittest
import test_original_runtime as fixtures
from backend.live import messages_for


class ModelInputCompactionTests(unittest.TestCase):
    def fixture(self):
        run=fixtures.OriginalRuntimeTests().run_fixture()
        run.drafts=[{'content':{'selected_title':'标题','body':'这款桌子长120厘米。','cta':'核对尺寸','tags':[]}}]
        provenance={'visibility':'public_report','metrics_basis':'reported_at_publication',
            'report_published_date':'2025-01-01','report_statistical_period':'2024',
            'current_platform_metrics_verified':False,'original_post_read':False,
            'content_scope':'公开报告中的局部文字摘录','excerpt_kind':'reported_example',
            'permission_audit':{'qa_mapping':'audit-only '*1000},'sample_batch':'x'*2000}
        for index,source in enumerate(run.context['evidence']):
            source.update(title='参考资料'+str(index),document_id='doc'+str(index),version=1,
                url='https://example.com/'+str(index),page=3,offset=25,source_type='text',
                evidence_role='expression_reference' if index==1 else 'source_material',
                classification={'material_type':source['material_type']},
                case_ref={'document_id':'doc'+str(index),'version':1,'platform':'xiaohongshu',
                    'published_at':None,'observed_at':'2025-01-02','verification':'未独立核验',
                    'source_method':'report_excerpt','metrics':{'likes':None},'provenance':copy.deepcopy(provenance),
                    'body_hash':'x'*64,'sample_batch':'batch '*1000,'permission':'audit '*1000})
        run.context['creation_retrieval'].update(gaps=['原笔记未读取，互动数未核实'],
            engine='bm25',filters={'audit_only':'filter '*1000},limits={'audit_only':'limit '*1000},
            classification=run.context['creation_classification'],context_chars=1234)
        return run

    def test_all_eight_stages_keep_source_text_groups_identity_and_truth_limits(self):
        run=self.fixture();frozen=copy.deepcopy(run.context)
        expected={s['source_id']:s['text'] for s in run.context['evidence']}
        for stage in ('audience','research','strategy','outline','hook','title','body','review'):
            with self.subTest(stage=stage):
                messages,data=messages_for(run,stage)
                self.assertEqual(json.loads(messages[1]['content']),data)
                self.assertEqual(set(data['creation_retrieval']),{'methods','examples','facts','gaps'})
                self.assertEqual([s['source_id'] for s in data['materials']],['user-material','fact:1'])
                self.assertEqual(data['materials'][0]['text'],'桌面为白色。')
                self.assertEqual(data['materials'][1]['text'],expected['fact:1'])
                self.assertEqual(data['creation_retrieval']['methods'][0]['text'],expected['method:1'])
                example=data['creation_retrieval']['examples'][0]
                self.assertEqual(example['text'],expected['example:1'])
                self.assertEqual(example['case_ref']['provenance']['original_post_read'],False)
                self.assertEqual(example['case_ref']['provenance']['content_scope'],'公开报告中的局部文字摘录')
                self.assertEqual(data['creation_retrieval']['gaps'],frozen['creation_retrieval']['gaps'])
                reference=data['retrieved_references'][0]
                self.assertEqual({k:v for k,v in reference.items() if k!='case_ref'},
                                 {k:example[k] for k in ('source_id','title','document_id','version','url','evidence_role')})
                self.assertEqual(reference['case_ref']['observed_at'],example['case_ref']['observed_at'])
                self.assertEqual(reference['case_ref']['verification'],example['case_ref']['verification'])
                self.assertNotIn('sample_batch',reference['case_ref'])
                self.assertEqual(run.context,frozen)
                example['case_ref']['metrics']['likes']=999
                data['creation_classification']['domains'].append('mutated')
                self.assertEqual(run.context,frozen)

    def test_long_audit_metadata_shrinks_without_modifying_frozen_audit(self):
        run=self.fixture();frozen=copy.deepcopy(run.context)
        _,data=messages_for(run,'body')
        old=json.dumps(run.context['creation_retrieval'],ensure_ascii=False)
        projected=json.dumps(data['creation_retrieval'],ensure_ascii=False)
        self.assertLess(len(projected),len(old)*0.15)
        self.assertNotIn('permission_audit',projected)
        self.assertNotIn('sample_batch',projected)
        self.assertEqual(run.context,frozen)

    def test_legacy_unclassified_reference_metadata_is_unchanged(self):
        run=self.fixture();run.context.pop('creation_classification')
        _,data=messages_for(run,'research')
        self.assertIn('sample_batch',data['retrieved_references'][0]['case_ref'])
        self.assertIn('permission_audit',data['retrieved_references'][0]['case_ref']['provenance'])

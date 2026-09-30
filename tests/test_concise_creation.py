"""Context projection saves tokens without dropping sources or review issues."""
import copy
import json
import unittest
from types import SimpleNamespace
from backend.live import messages_for, schema

class ConciseCreationTests(unittest.TestCase):
    def fixture(self):
        source='原始事实材料，不能丢失。'*30
        return SimpleNamespace(context={'topic':'测试','audience':'新手','tone':'朴实','allow_hypothesis':True,'material':source,'operations':{'profile':{'banned':'不能保证效果'}}},
            branches={'research':{'data':dict(schema('research'),sources=[source]*8,topic_card={'extra':'展示信息'*500})},'audience':{'data':schema('audience')}},
            artifacts=[{'stage':'strategy','value':dict(schema('strategy'),content_brief={'duplicate':'重复'*1000})}, {'stage':'outline','value':['步骤一','步骤二']},{'stage':'hook','value':'短开头'}, {'stage':'title','value':schema('title')}],
            drafts=[{'content':{'selected_title':'标题','body':'正文','cta':'问题','tags':[]}}],review={'issues':[{'issue_id':'important','reason':'不可删除'}]},prior_review={'issues':[{'issue_id':'prior','reason':'必须复核'}]})

    def test_stage_context_excludes_duplicate_sources_and_future_stages(self):
        run=self.fixture();before=copy.deepcopy(run.__dict__)
        messages,data=messages_for(run,'hook')
        self.assertEqual(set(data['upstream']),{'strategy','outline'})
        self.assertNotIn('sources',data['branches']['research']['data'])
        self.assertNotIn('content_brief',data['upstream']['strategy'])
        self.assertTrue(data['materials']);self.assertEqual(data['operations'],run.context['operations'])
        self.assertEqual(run.__dict__,before)
        self.assertNotIn('展示信息',messages[1]['content']);self.assertNotIn('重复重复',messages[1]['content'])

    def test_review_and_revision_keep_draft_issues_and_sources(self):
        run=self.fixture()
        for stage,previous in [('review',run.prior_review),('revise',run.review)]:
            _,data=messages_for(run,stage)
            self.assertEqual(data['draft'],run.drafts[-1]['content'])
            self.assertEqual(data['previous_review'],previous)
            self.assertEqual(data['upstream'],{})
            self.assertTrue(data['materials'])
            self.assertIn('prohibited_claims',data['branches']['research']['data'])

    def test_body_keeps_selected_title_and_concise_instruction(self):
        messages,data=messages_for(self.fixture(),'body')
        self.assertEqual(data['upstream']['title']['selected'],'候选一')
        self.assertIn('150至250字',messages[0]['content'])
        self.assertIn('全部8项',messages[0]['content'])

    def test_reaudit_prompt_only_tracks_immediate_issue_ids(self):
        run=self.fixture()
        run.prior_review['previous_issue_results']=[{'issue_id':'obsolete','result':'unresolved'}]
        before=copy.deepcopy(run.prior_review)
        messages,data=messages_for(run,'review')
        self.assertEqual(data['required_previous_issue_ids'],['prior'])
        self.assertNotIn('previous_issue_results',data['previous_review'])
        self.assertNotIn('obsolete',messages[1]['content'])
        self.assertIn('"issue_id": "prior", "result": "unresolved"',messages[0]['content'])
        self.assertIn('必须needs_human',messages[0]['content'])
        self.assertEqual(run.prior_review,before)

"""Context projection saves tokens without dropping sources or review issues."""
import copy
import json
import unittest
from types import SimpleNamespace
from backend.live import messages_for, normalize, schema
from backend.contracts import DomainError

class ConciseCreationTests(unittest.TestCase):
    def test_title_prompt_requires_exactly_five_pairs_and_only_title_fields(self):
        run=self.fixture();before=copy.deepcopy(run.__dict__)
        messages,_=messages_for(run,'title')
        self.assertIn('只输出candidates、selected、note、reasons四个字段',messages[0]['content'])
        self.assertIn('各恰好5项（不是6项）',messages[0]['content'])
        self.assertIn('按索引一一对应',messages[0]['content'])
        self.assertEqual(set(schema('title')),{'candidates','selected','note','reasons'})
        self.assertEqual(run.__dict__,before)
        other,_=messages_for(run,'hook')
        self.assertNotIn('各恰好5项（不是6项）',other[0]['content'])

    def test_title_six_pairs_remain_rejected_without_truncation(self):
        run=self.fixture();value=schema('title')
        value['candidates'].append('候选六');value['reasons'].append('候选六理由')
        before=copy.deepcopy(value)
        with self.assertRaises(DomainError):normalize(run,'title',value)
        self.assertEqual(value,before)
        valid=schema('title')
        self.assertEqual(normalize(run,'title',valid),valid)

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

    def test_reader_copy_stages_separate_internal_notes_without_changing_schema(self):
        run=self.fixture()
        for stage in ('outline','hook','title','body','revise'):
            with self.subTest(stage=stage):
                messages,_=messages_for(run,stage)
                instruction=messages[0]['content']
                self.assertIn('面向目标读者创作',instruction)
                self.assertIn('网页发布时间为空',instruction)
                self.assertIn('review.human_questions',instruction)
                self.assertIn('不能凭空替博主承诺后续更新',instruction)
                self.assertIn('读者有用的适用条件、真实来源引用和必要的不确定性应保留',instruction)
                self.assertNotIn('发布时间为空时说明时效未知',instruction)
        for stage in ('body','revise'):
            self.assertEqual(set(schema(stage)),{'selected_title','body','cta','tags'})

    def test_research_requires_core_step_evidence_and_review_routes_missing_sources(self):
        research,_=messages_for(self.fixture(),'research')
        self.assertIn('材料只列产品名或背景、没有步骤依据，必须core_gap=true',research[0]['content'])
        self.assertIn('模型常识与“多数流程”不能冒充材料依据',research[0]['content'])
        review,_=messages_for(self.fixture(),'review')
        self.assertIn('不是删掉免责声明就视为事实问题已解决',review[0]['content'])
        self.assertIn('缺口请求写human_questions',review[0]['content'])
        self.assertIn('按usefulness_and_readability及标题与正文承诺的一致性审查',review[0]['content'])

    def test_reader_motivation_flows_from_strategy_through_title_to_body(self):
        run=self.fixture()
        instructions={stage:messages_for(run,stage)[0][0]['content']
                      for stage in ('strategy','hook','title','body','review')}
        self.assertIn('promise给材料足以支持、正文能够兑现的看点或收益',instructions['strategy'])
        self.assertIn('首句抓具体场景、读者痛点或有依据的反差',instructions['hook'])
        self.assertIn('不写自我介绍、“这期只讲”或研究过程',instructions['hook'])
        self.assertIn('五个候选在角度与句式上有实质区别',instructions['title'])
        self.assertIn('selected的承诺必须由材料和计划正文兑现',instructions['title'])
        self.assertIn('禁止夸张数字、制造恐惧、疗效保证、虚构亲历或爆款承诺',instructions['title'])
        self.assertIn('正文必须兑现标题承诺',instructions['body'])
        self.assertIn('核对正文首句承接与正文实际兑现标题承诺',instructions['review'])
        _,title_data=messages_for(run,'title')
        _,body_data=messages_for(run,'body')
        self.assertEqual(title_data['upstream']['strategy'],body_data['upstream']['strategy'])
        self.assertEqual(title_data['upstream']['hook'],body_data['upstream']['hook'])
        self.assertEqual(body_data['upstream']['title']['selected'],'候选一')

    def test_hook_and_title_receive_bounded_reader_motivation_without_future_title(self):
        run=self.fixture()
        audience=run.branches['audience']['data']
        audience['pain_points']=['问题'+str(i) for i in range(5)]
        audience['content_opportunities']=['机会'+str(i) for i in range(5)]
        before=copy.deepcopy(audience)
        for stage in ('hook','title'):
            _,data=messages_for(run,stage)
            projected=data['branches']['audience']['data']
            self.assertEqual(projected['pain_points'],audience['pain_points'][:3])
            self.assertEqual(projected['content_opportunities'],audience['content_opportunities'][:3])
            self.assertNotIn('title',data['upstream'])
        self.assertEqual(audience,before)

"""Free simulation title guards; no model calls or historical draft rewrites."""
import copy
from types import SimpleNamespace
import unittest
from backend.demo import _make_content,validate_brief,advance
from backend.workflow import Run

class SimulationTitleTests(unittest.TestCase):
    def task(self,topic,scenario='standard',platform='xiaohongshu'):
        context=validate_brief({'topic':topic,'audience':'新手','tone':'清楚','material':'用户给定事实','scenario':scenario,'allow_hypothesis':True})
        context['operations']={'platform':platform};context['material_policy']='available_only'
        return SimpleNamespace(context=context,artifacts=[])
    def test_all_five_xiaohongshu_candidates_and_selected_fit_for_long_and_unicode_topics(self):
        for topic in ('免费流程验收 罗技M650连接方式','超长产品资料介绍与功能说明'*6,'😀'*25,'短主题'):
            for scenario in ('standard','revision','missing'):
                with self.subTest(topic=topic,scenario=scenario):
                    value=_make_content(self.task(topic,scenario),'title')
                    self.assertEqual(len(value['candidates']),5)
                    self.assertEqual(len(set(value['candidates'])),5)
                    self.assertIn(value['selected'],value['candidates'])
                    self.assertTrue(all(0<len(title)<=20 for title in value['candidates']))
                    self.assertEqual('必爆' in value['selected'],scenario=='revision')
    def test_short_topics_preserve_existing_templates_and_other_platforms_unchanged(self):
        short=_make_content(self.task('整理'),'title')
        self.assertEqual(short['selected'],'整理：从一个小步骤开始')
        topic='免费流程验收 罗技M650连接方式'
        for platform in ('douyin',None):
            result=_make_content(self.task(topic,platform=platform),'title')
            self.assertEqual(result['selected'],topic+'：从一个小步骤开始')
            self.assertGreater(len(result['selected']),20)
    def test_free_simulation_flow_keeps_bounded_title_through_review_and_revision(self):
        for scenario in ('standard','revision'):
            task=self.task('免费流程验收 罗技M650连接方式',scenario)
            run=Run('fixture-owner','fixture-snapshot',context=task.context)
            for _ in range(12):
                if run.run_status=='WAITING_USER':break
                advance(run)
            self.assertEqual(run.wait_reason,'final_confirmation')
            self.assertTrue(run.drafts)
            self.assertTrue(all(len(draft['content']['selected_title'])<=20 for draft in run.drafts))
            self.assertNotIn('必爆',run.drafts[-1]['content']['selected_title'])
            self.assertTrue(all(node.get('model_calls',0)==0 for node in run.node_runs))

    def test_historical_title_artifact_and_draft_are_not_rewritten_by_new_generation(self):
        task=self.task('超长话题'*8)
        old='旧任务保留的超过二十字标题不会被新生成步骤自动覆盖'
        task.artifacts=[{'stage':'title','value':{'selected':old}},{'stage':'hook','value':'旧开头'}]
        before=copy.deepcopy(task.artifacts)
        _make_content(task,'title')
        self.assertEqual(task.artifacts,before)
        self.assertEqual(_make_content(task,'body')['selected_title'],old)

if __name__=='__main__':unittest.main()

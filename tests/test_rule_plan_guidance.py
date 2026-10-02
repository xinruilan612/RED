"""Free weekly suggestions stay distinct, profile-grounded and reversible."""
import unittest
from datetime import date
from uuid import UUID

from backend.accounts import new_account
from backend.analytics import refresh_plans
from backend.contracts import DomainError
from backend.planning import make_plan, update_plan, update_task


class RulePlanGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.account = new_account('account-one', '学习清单', 'xiaohongshu')
        self.account['profile'].update(
            positioning='学生学习工具实践', audience='第一次整理课程文件的同学',
            pillars='步骤教程', goal='验证方向', resources='每周 2–4 小时、主要用手机拍摄')
        self.state = dict(accounts=[self.account], memories=[], plans=[], publications=[])
        self.request = dict(account_id=self.account['id'], week_start='2026-09-28', source_type='manual')

    def create(self):
        make_plan(self.state, self.request, '2026-09-28T09:00:00+00:00')
        return self.state['plans'][0]

    def test_one_to_seven_tasks_are_distinct_even_with_a_single_pillar(self):
        for count in range(1, 8):
            with self.subTest(count=count):
                self.state['plans'] = []
                self.account['profile']['weekly_frequency'] = count
                tasks = self.create()['tasks']
                self.assertEqual(len(tasks), count)
                for field in ('id', 'date', 'title', 'angle', 'action', 'success_signal'):
                    self.assertEqual(len({task[field] for task in tasks}), count, field)
                for task in tasks:
                    UUID(task['id'])
                    self.assertEqual(task['pillar'], '步骤教程')
                    self.assertIn('步骤教程', task['title'])
                    self.assertIn('第一次整理课程文件的同学', task['action'])
                    self.assertIn('控制制作量', task['title'])
                    self.assertIn('手机可完成', task['title'])
                    offset = (date.fromisoformat(task['date']) - date.fromisoformat(self.request['week_start'])).days
                    self.assertTrue(0 <= offset <= 6)
                    self.assertEqual(task['status'], 'planned')
                    self.assertIsNone(task['publication_id'])

    def test_free_rules_have_honest_execution_metadata_and_no_ai_claim(self):
        plan = self.create()
        self.assertEqual(plan['execution'], dict(stage='operations_plan', mode='rules',
                                                algorithm='profile_rules_v2', model_calls=0))
        self.assertNotIn('model', plan['execution'])
        self.assertEqual(plan['profile_revision'], self.account['revision'])
        self.assertEqual(plan['profile_snapshot']['audience'], self.account['profile']['audience'])
        self.assertIn('验证方向', plan['tasks'][0]['reason'])
        self.assertIn('一次只测试一个表达点', plan['tasks'][0]['reason'])
        self.assertIn('学生学习工具实践', plan['tasks'][0]['reason'])
        self.assertTrue(any('不是已验证' in gap for gap in plan['data_gaps']))
        self.assertIn('不会自动', plan['limitation'])
        self.assertEqual(plan['source_type'], 'manual')

    def test_missing_profile_prompts_for_materials_instead_of_inventing_evidence(self):
        self.account = new_account('account-empty', '未设置账号', 'douyin')
        self.state['accounts'] = [self.account]
        self.request['account_id'] = self.account['id']
        self.account['profile']['weekly_frequency'] = 7
        plan = self.create()
        self.assertEqual(len(plan['data_gaps']), 5)
        for task in plan['tasks']:
            self.assertEqual(task['pillar'], '常青内容')
            self.assertIn('先明确目标读者', task['action'])
            self.assertIsNone(task['memory_ref'])
            self.assertTrue(all(ref.startswith('profile:') for ref in task['basis_refs']))
            self.assertIn('暂无历史效果依据', task['reason'])
        self.assertIn('不虚构亲历案例', plan['tasks'][4]['action'])
        self.assertIn('待验证的假设', plan['tasks'][5]['action'])
        self.assertIn('没有表现数据', plan['tasks'][6]['success_signal'])

    def test_only_same_account_and_source_accepted_memory_is_used_once(self):
        self.state['memories'] = [
            dict(id='other-account', account_id='different', source_type='manual', status='accepted', text='其他账号'),
            dict(id='simulated', account_id=self.account['id'], source_type='simulation', status='accepted', text='演示经验'),
            dict(id='revoked', account_id=self.account['id'], source_type='manual', status='revoked', text='已撤销'),
            dict(id='accepted', account_id=self.account['id'], source_type='manual', status='accepted', text='先解释准备条件'),
        ]
        plan = self.create()
        self.assertEqual(plan['memory_refs'], ['accepted'])
        self.assertEqual([task['memory_ref'] for task in plan['tasks']], ['accepted', None, None])
        self.assertIn('memory:accepted', plan['tasks'][0]['basis_refs'])
        for task in plan['tasks'][1:]:
            self.assertFalse(any(ref.startswith('memory:') for ref in task['basis_refs']))
        self.state['memories'][-1]['status'] = 'revoked'
        refresh_plans(self.state)
        self.assertEqual(plan['status'], 'needs_review')
        with self.assertRaises(DomainError):
            update_plan(self.state, dict(id=plan['id'], status='accepted'))

    def test_task_edit_accept_revoke_and_profile_change_keep_existing_guards(self):
        plan = self.create()
        with self.assertRaises(DomainError):
            self.create()
        update_plan(self.state, dict(id=plan['id'], status='accepted'))
        task = plan['tasks'][0]
        edit = dict(plan_id=plan['id'], task_id=task['id'], title='我的课程文件命名步骤',
                    date=task['date'], status='done', publication_id=None)
        update_task(self.state, edit)
        self.assertEqual(task['title'], edit['title'])
        self.assertEqual(task['status'], 'done')
        with self.assertRaises(DomainError):
            update_task(self.state, {**edit, 'date': '2026-10-05'})
        with self.assertRaises(DomainError):
            update_task(self.state, {**edit, 'publication_id': 'not-owned'})
        self.account['revision'] += 1
        refresh_plans(self.state)
        self.assertEqual(plan['status'], 'needs_review')
        with self.assertRaises(DomainError):
            update_task(self.state, edit)
        update_plan(self.state, dict(id=plan['id'], status='revoked'))
        self.assertEqual(plan['status'], 'revoked')


if __name__ == '__main__':
    unittest.main()

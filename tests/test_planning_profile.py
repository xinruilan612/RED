import unittest

from backend.planning import _goal_action


class PlanningGoalTests(unittest.TestCase):
    def test_dynamic_goals_map_to_relevant_weekly_actions(self):
        follower = _goal_action('吸引摄影兴趣用户关注', '摄影作品展示', [])
        booking = _goal_action('获取约拍咨询', '约拍案例', [])
        sales = _goal_action('提升商品浏览与成交', '穿搭展示', [])
        trial = _goal_action('引导试用 / 注册', '功能实操演示', [])
        self.assertIn('拍摄前后对比', follower)
        self.assertIn('下一步', booking)
        self.assertIn('真实使用场景', sales)
        self.assertIn('下一步', trial)


if __name__ == '__main__':
    unittest.main()

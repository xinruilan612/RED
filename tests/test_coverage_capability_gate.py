"""Regression from observed pilot failure, not held-out quality evidence."""
import unittest

from backend.creation_algorithms import coverage_evidence_matches


class CapabilityGateTests(unittest.TestCase):
    def test_port_list_does_not_answer_charging_video_or_microphone_capability(self):
        quote='机身正面提供两个支持USB 3的USB-C口和耳机插孔。'
        for question in ('正面两个USB-C口是否支持视频输出或充电？',
                         '耳机孔是否支持模拟麦克风输入？',
                         '正面USB-C接口可以给电脑供电吗？'):
            self.assertFalse(coverage_evidence_matches(question,quote),question)

    def test_port_list_does_not_answer_direct_or_simultaneous_use(self):
        quote='M4版本背面使用三个雷雳4端口。'
        for question in ('我的显示器带雷雳4输入，能直连M4背面接口吗？',
                         '三个雷雳4接口能否同时接显示器、硬盘和扩展坞？'):
            self.assertFalse(coverage_evidence_matches(question,quote),question)

    def test_explicit_location_can_still_answer_location(self):
        self.assertTrue(coverage_evidence_matches('雷雳4端口位于什么位置？','雷雳4端口位于机身背面。'))

    def test_explicit_capability_survives_with_all_requested_aspects(self):
        question='正面USB-C接口是否支持视频输出和充电？'
        self.assertFalse(coverage_evidence_matches(question,'正面USB-C接口支持视频输出。'))
        self.assertTrue(coverage_evidence_matches(question,'正面USB-C接口支持视频输出和充电。'))

    def test_unknown_is_not_positive_coverage(self):
        self.assertFalse(coverage_evidence_matches('USB-C接口是否支持充电？','未提供USB-C接口的充电资料。'))

    def test_plug_and_comfort_require_their_own_records(self):
        self.assertFalse(coverage_evidence_matches('USB接收器是否需要安装驱动？','产品配有USB接收器。'))
        self.assertFalse(coverage_evidence_matches('尺寸对应的握感是否舒适？','产品尺寸为100毫米。'))


if __name__=='__main__':unittest.main()

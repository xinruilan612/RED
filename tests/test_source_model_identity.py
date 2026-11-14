"""Product identity matching stays conservative across formatting variants."""
import unittest

from backend.sources import model_terms, related_model_match, topic_match


class SourceModelIdentityTests(unittest.TestCase):
    def test_numeric_slim_and_lite_spacing_and_hyphens_are_equivalent(self):
        for suffix in ('Slim', 'Lite'):
            for spelling in ('ZX3'+suffix, 'ZX3 '+suffix, 'ZX 3-'+suffix, 'ZX-3-'+suffix):
                with self.subTest(spelling=spelling):
                    self.assertTrue(topic_match('品牌ZX3'+suffix+'参数', spelling+' 技术参数'))
                    self.assertTrue(topic_match(spelling+' 参数', 'ZX3'+suffix+' 技术参数'))

    def test_numeric_variants_are_never_same_identity(self):
        for text in ('ZX3', 'ZX3Pro', 'ZX3 Lite', 'ZX3SlimPlus', 'ZX4Slim'):
            with self.subTest(text=text):
                self.assertFalse(topic_match('ZX3 Slim 参数', text+' 技术参数'))
        self.assertTrue(related_model_match('ZX3 Slim', 'ZX3 Pro'))
        self.assertFalse(related_model_match('ZX3 Slim', 'ZX4 Slim'))

    def test_named_models_require_family_and_complete_variant(self):
        self.assertEqual(model_terms('品牌 T Air Lite 换袋资料'), ['T Air Lite'])
        for text in ('T Air Lite 产品说明', 'T-Air-Lite 产品说明', 't air lite 产品说明'):
            with self.subTest(text=text):
                self.assertTrue(topic_match('品牌 T Air Lite 参数', text))
        for text in ('全新商品 Air 系列', 'Lite 新品', 'X Air Lite 参数', 'T Air 参数', 'T Air Max 参数'):
            with self.subTest(text=text):
                self.assertFalse(topic_match('品牌 T Air Lite 参数', text))

    def test_rule_is_not_specific_to_a_brand(self):
        self.assertTrue(topic_match('MapleBook Air 产品', 'MapleBook-Air 使用指南'))
        self.assertFalse(topic_match('MapleBook Air 产品', 'AnotherBook Air 产品'))
        self.assertEqual(model_terms('Air Lite'), [])
        self.assertEqual(model_terms('普通中文产品资料'), [])
        self.assertTrue(topic_match('洗衣机安装条件', '洗衣机安装条件说明'))

    def test_existing_pro_identity_constraints_still_hold(self):
        self.assertTrue(topic_match('品牌QX7Pro参数', 'QX 7 Pro - 技术参数'))
        self.assertFalse(topic_match('品牌QX7Pro参数', 'QX 7 参数'))
        self.assertFalse(topic_match('品牌QX7Pro参数', 'QX 7P 参数'))


if __name__ == '__main__':
    unittest.main()

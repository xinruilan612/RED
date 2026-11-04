"""Payload-only Qwen JSON compatibility; never calls an actual provider."""
import copy
import unittest
from unittest.mock import patch
from backend.contracts import DomainError
from backend.provider import ConnectedModel, effective_json_mode


class QwenJsonModeTests(unittest.TestCase):
    def connection(self, **changes):
        return {'provider':'qwen','model':'qwen-plus','protocol':'openai','json_mode':False,
                'base_url':'https://dashscope.aliyuncs.com/compatible-mode/v1',
                'version':4,'run_budget_usd':1,'day_budget_usd':5,**changes}

    def packet(self, text='{"ok":true}'):
        return {'choices':[{'finish_reason':'stop','message':{'content':text}}],
                'usage':{'total_tokens':10,'prompt_tokens':7,'completion_tokens':3}}

    def payload(self,item):
        with patch('backend.provider.connected_request',return_value=self.packet()) as request:
            value,tokens,_=ConnectedModel(item,'test-only').complete_result([{'role':'system','content':'只输出JSON对象'}])
        self.assertEqual((value,tokens),({'ok':True},10))
        self.assertEqual(request.call_count,1)
        return request.call_args.args[2]

    def test_exact_official_route_forces_json_without_mutating_connection(self):
        item=self.connection();before=copy.deepcopy(item)
        self.assertTrue(effective_json_mode(item))
        self.assertEqual(self.payload(item)['response_format'],{'type':'json_object'})
        self.assertEqual(item,before)
        self.assertFalse(item['json_mode'])

    def test_other_models_providers_hosts_regions_and_paths_remain_explicit(self):
        variants=[{'model':'qwen-max'},{'model':'qwen-plus-latest'},
                  {'model':'qwen-plus-2025-12-01'},{'provider':'custom'},
                  {'base_url':'https://gateway.example.com/v1'},
                  {'base_url':'https://dashscope-intl.aliyuncs.com/compatible-mode/v1'},
                  {'base_url':'https://dashscope-us.aliyuncs.com/compatible-mode/v1'},
                  {'base_url':'https://dashscope.aliyuncs.com/other/v1'},
                  {'base_url':'https://dashscope.aliyuncs.com.example.org/compatible-mode/v1'}]
        for change in variants:
            with self.subTest(change=change):
                item=self.connection(**change)
                self.assertFalse(effective_json_mode(item))
                self.assertNotIn('response_format',self.payload(item))
                item['json_mode']=True
                self.assertEqual(self.payload(item)['response_format'],{'type':'json_object'})

    def test_other_protocols_do_not_get_automatic_mode(self):
        for protocol in ('responses','anthropic'):
            self.assertFalse(effective_json_mode(self.connection(protocol=protocol)))

    def test_malformed_response_still_rejects_without_retry(self):
        with patch('backend.provider.connected_request',return_value=self.packet('{"ok":')) as request:
            with self.assertRaises(DomainError) as raised:
                ConnectedModel(self.connection(),'test-only').complete_result([{'role':'system','content':'JSON only'}])
        self.assertEqual(raised.exception.code,'MODEL_OUTPUT_INVALID')
        self.assertEqual(request.call_count,1)

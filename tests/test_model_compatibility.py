"""Offline protocol/endpoint regressions; never use a user's API key."""
import json
import unittest
from unittest.mock import Mock, patch
import test_model_connections as connections
from backend.contracts import DomainError
from backend.model_connections import base_url, CONNECTION_DEFAULTS
from backend.provider import ConnectedModel, connected_request


class ModelCompatibilityTests(unittest.TestCase):
    setUp=connections.ConnectionTests.setUp
    save=connections.ConnectionTests.save

    def test_documented_model_candidates_do_not_restrict_custom_ids(self):
        catalog={item['id']:item for item in self.models.public('alice')['catalog']}
        self.assertIn('qwen-plus',catalog['qwen']['models'])
        self.assertEqual(catalog['custom']['models'],[])
        item=self.save(provider='qwen',model='account-specific-future-model')
        self.assertEqual(item['model'],'account-specific-future-model')

    def test_simple_save_defaults_and_edit_preserves_custom_budget(self):
        with patch('backend.provider.connected_request') as request:
            item=self.models.save('alice',{'provider':'qwen','model':' qwen-example ','api_key':' user-key '})
            self.assertEqual(item['model'],'qwen-example')
            self.assertFalse(item['json_mode'])
            self.assertEqual(item['protocol'],'openai')
            for name,value in CONNECTION_DEFAULTS.items():self.assertEqual(item[name],value)
            changed=self.save(id=item['id'],version=1,run_budget_usd=2,day_budget_usd=7)
            edited=self.models.save('alice',{'id':changed['id'],'version':2,'provider':'qwen','model':'other'})
            self.assertEqual((edited['run_budget_usd'],edited['day_budget_usd']),(2,7))
            request.assert_not_called()

    def test_endpoint_normalization_and_protocol_inference(self):
        for endpoint,protocol in [('chat/completions','openai'),('responses','responses'),('messages','anthropic')]:
            with self.subTest(endpoint=endpoint):
                item=self.save(provider='custom',base_url=' https://gateway.example.com/custom/v1/'+endpoint+'/// ')
                self.assertEqual(item['base_url'],'https://gateway.example.com/custom/v1')
                self.assertEqual(item['protocol'],protocol)
        self.assertEqual(base_url('https://api.openai.com/'),'https://api.openai.com/v1')
        self.assertEqual(base_url('https://api.anthropic.com/'),'https://api.anthropic.com/v1')
        self.assertEqual(base_url('https://gateway.example.com/custom'),'https://gateway.example.com/custom')
        with self.assertRaises(DomainError):self.save(provider='custom',base_url='https://gateway.example.com/v1/messages',protocol='responses')
        with self.assertRaises(DomainError):self.save(protocol='unknown')
        with self.assertRaises(DomainError):self.save(protocol='anthropic',json_mode=True)

    def response(self,protocol,text='{"ok":true}',**changes):
        if protocol=='responses':packet={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':text}]}],'usage':{'input_tokens':7,'output_tokens':3,'total_tokens':10}}
        elif protocol=='anthropic':packet={'stop_reason':'end_turn','content':[{'type':'text','text':text}],'usage':{'input_tokens':7,'output_tokens':3}}
        else:packet={'choices':[{'finish_reason':'stop','message':{'content':text}}],'usage':{'prompt_tokens':7,'completion_tokens':3,'total_tokens':10}}
        packet.update(changes);return packet

    def test_all_custom_protocols_accept_fenced_json_without_forced_format(self):
        for protocol,suffix in [('openai','chat/completions'),('responses','responses'),('anthropic','messages')]:
            item=self.save(provider='custom',protocol=protocol,base_url='https://gateway.example.com/v1')
            with self.subTest(protocol=protocol),patch('backend.provider.connected_request',return_value=self.response(protocol,'```json\n{"ok":true}\n```')) as request:
                value,tokens,meta=ConnectedModel(item,'test-key').complete_result([{'role':'system','content':'JSON only'},{'role':'user','content':'test'}])
                self.assertEqual(value,{'ok':True});self.assertEqual(tokens,10)
                self.assertEqual(request.call_args.args[0],'https://gateway.example.com/v1/'+suffix)
                payload=request.call_args.args[2]
                self.assertNotIn('response_format',payload);self.assertNotIn('text',payload)
                self.assertNotIn('thinking',payload);self.assertNotIn('enable_thinking',payload)
                self.assertIn('x-api-key' if protocol=='anthropic' else 'Authorization',request.call_args.args[1])

    def test_explicit_json_mode_and_modern_token_parameter(self):
        for protocol in ('openai','responses'):
            item=self.save(provider='custom',model='openai/gpt-5',protocol=protocol,json_mode=True,base_url='https://gateway.example.com/v1')
            with patch('backend.provider.connected_request',return_value=self.response(protocol)) as request:
                ConnectedModel(item,'test-key').complete_result([{'role':'user','content':'JSON only'}])
            payload=request.call_args.args[2]
            if protocol=='openai':
                self.assertEqual(payload['response_format'],{'type':'json_object'})
                self.assertIn('max_completion_tokens',payload);self.assertNotIn('max_tokens',payload)
            else:self.assertEqual(payload['text']['format'],{'type':'json_object'})

    def test_non_json_truncated_or_usage_missing_fail_without_retry(self):
        item=self.save()
        packets=[self.response('openai','Here is your answer: {"ok":true}'),
                 self.response('openai','{"ok":'),self.response('openai',usage={}),
                 self.response('openai',usage={'total_tokens':True}),
                 self.response('openai',usage={'prompt_tokens':7,'completion_tokens':3,'total_tokens':99}),
                 {'choices':[{'finish_reason':'length','message':{'content':'{"ok":true}'}}],'usage':{'total_tokens':10}}]
        for packet in packets:
            with self.subTest(packet=packet),patch('backend.provider.connected_request',return_value=packet) as request:
                with self.assertRaises(DomainError):ConnectedModel(item,'test-key').complete_result([{'role':'user','content':'test'}])
                self.assertEqual(request.call_count,1)

    def test_qwen_sync_flag_is_scoped_to_official_hybrid_models(self):
        for model,url,expected in [('qwen3-32b','https://dashscope.aliyuncs.com/compatible-mode/v1',True),
                                   ('qwen3-235b-a22b','https://dashscope-intl.aliyuncs.com/compatible-mode/v1',True),
                                   ('qwen3-32b','https://gateway.example.com/v1',False),
                                   ('qwen3-235b-a22b-thinking-2507','https://dashscope.aliyuncs.com/compatible-mode/v1',False),
                                   ('qwen2.5-72b-instruct','https://dashscope.aliyuncs.com/compatible-mode/v1',False)]:
            item=self.save(provider='qwen',model=model,base_url=url)
            with self.subTest(model=model,url=url),patch('backend.provider.connected_request',return_value=self.response('openai')) as request:
                ConnectedModel(item,'test-key').complete_result([{'role':'user','content':'JSON only'}])
                self.assertEqual('enable_thinking' in request.call_args.args[2],expected)
                if expected:self.assertIs(request.call_args.args[2]['enable_thinking'],False)

    def test_content_parts_and_reported_split_usage_are_supported(self):
        packet=self.response('openai',usage={'prompt_tokens':7,'completion_tokens':3})
        packet['choices'][0]['message']['content']=[{'type':'text','text':'{"ok":'},{'type':'text','text':'true}'}]
        with patch('backend.provider.connected_request',return_value=packet):
            value,tokens,_=ConnectedModel(self.save(),'test-key').complete_result([{'role':'user','content':'test'}])
        self.assertEqual((value,tokens),({'ok':True},10))

    def test_vendor_errors_keep_codes_and_messages_but_remove_credentials(self):
        for status,code,message in [(400,'unsupported_parameter','response_format is not supported'),
                    (401,'invalid_api_key','Invalid API key user-key-private'),
                    (402,'insufficient_balance','Balance is insufficient'),
                    (404,'model_not_found','Requested model is not available'),
                    (429,'insufficient_quota','Quota exceeded')]:
            response=Mock(status=status)
            response.read.return_value=json.dumps({'error':{'code':code,'message':message}}).encode()
            connection=Mock();connection.getresponse.return_value=response
            with self.subTest(status=status),patch('socket.getaddrinfo',return_value=[(2,1,6,'',('1.1.1.1',443))]),patch('http.client.HTTPSConnection',return_value=connection):
                with self.assertRaises(DomainError) as caught:connected_request('https://gateway.example.com/v1/chat/completions',{'Authorization':'Bearer user-key-private'}, {})
                self.assertIn('HTTP '+str(status),str(caught.exception));self.assertIn(code,str(caught.exception))
                self.assertNotIn('user-key-private',str(caught.exception));self.assertEqual(connection.request.call_count,1)
                self.assertTrue(connection.close.called)

    def test_failed_probe_updates_only_current_version_and_retains_reservation(self):
        item=self.save()
        with patch('backend.provider.ConnectedModel.complete_result',side_effect=DomainError('PROVIDER_ERROR','HTTP 402 balance insufficient')):
            with self.assertRaises(DomainError):self.models.test('alice',item['id'],{'version':1,'acknowledge_cost':True})
        self.assertEqual(self.models.public('alice')['connections'][0]['test_status'],'failed')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT tokens,reserved,status FROM model_connection_tests').fetchone(),(None,512,'failed'))

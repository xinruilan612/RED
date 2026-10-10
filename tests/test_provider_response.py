"""Offline provider-envelope regressions; no network or paid calls."""
import json
import unittest
from unittest.mock import patch

from backend.provider import Config, DeepSeek, ProviderOutputError, decode_response, load_config


class ProviderResponseTests(unittest.TestCase):
    def test_five_revision_budget_defaults_preserve_explicit_lower_limits(self):
        from pathlib import Path
        from backend.contracts import PARAMETERS
        self.assertEqual(PARAMETERS['run_tokens_max'],160000)
        for config in (Config(),load_config(Path('/nonexistent-red-budget-test'),{})):
            self.assertEqual(config.run_budget_usd,0.20)
            self.assertEqual(config.day_budget_usd,0.50)
        explicit=Config(run_budget_usd=0.01,day_budget_usd=0.02)
        self.assertEqual((explicit.run_budget_usd,explicit.day_budget_usd),(0.01,0.02))

    def packet(self, content='{"answer":"可继续"}', **overrides):
        packet = {'id': 'request-123', 'choices': [{'finish_reason': 'stop',
                  'message': {'content': content}}],
                  'usage': {'total_tokens': 30, 'prompt_tokens': 20, 'completion_tokens': 10}}
        packet.update(overrides)
        return packet

    def complete(self, packet):
        raw = packet if isinstance(packet, bytes) else json.dumps(packet).encode()
        with patch('backend.provider.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = raw
            try:
                return DeepSeek(Config(api_key='secret-key')).complete_result([])
            finally:
                self.assertEqual(opener.return_value.open.call_count, 1)

    def test_plain_and_complete_fenced_json(self):
        for text in ('{"answer":"可继续"}', '```json\n{"answer":"可继续"}\n```',
                     '```\r\n{"answer":"可继续"}\r\n```',
                     '  ```JSON\n{"answer":"可继续"}\n```  '):
            with self.subTest(text=text):
                value, tokens, metadata = self.complete(self.packet(text))
                self.assertEqual(value, {'answer': '可继续'})
                self.assertEqual(tokens, 30)
                self.assertEqual(metadata, {'request_id': 'request-123', 'input_tokens': 20,
                                            'output_tokens': 10})

    def test_invalid_content_preserves_usage_without_raw_output(self):
        invalid = ['secret-key malformed', '{"a":', '[1]', 'null', '42',
                   'Here is JSON: {"a":1}', '```json\n{"a":1}\n```\nExplanation',
                   '```json\n{"a":1}', '{"a":1}{"b":2}', '{"a":1,"a":2}',
                   '{"a":NaN}', '{"a":Infinity}', '{"a":1e999}', None, [], {}]
        for content in invalid:
            with self.subTest(content=content):
                with self.assertRaises(ProviderOutputError) as caught:
                    self.complete(self.packet(content))
                error = caught.exception
                self.assertEqual(error.tokens, 30)
                self.assertEqual(error.metadata['input_tokens'], 20)
                self.assertEqual(error.diagnostic, 'content_invalid')
                self.assertNotIn('secret-key', str(error) + repr(error.__dict__))
                self.assertFalse(hasattr(error, 'response_text'))

    def test_empty_content_distinguished(self):
        with self.assertRaises(ProviderOutputError) as caught:
            self.complete(self.packet(' \n '))
        self.assertEqual(caught.exception.diagnostic, 'content_empty')
        self.assertEqual(caught.exception.tokens, 30)

    def test_truncated_valid_object_never_accepted(self):
        for reason, diagnostic in [('length', 'output_truncated'), ('content_filter', 'output_incomplete'),
                                    (None, 'output_incomplete')]:
            packet = self.packet()
            packet['choices'][0]['finish_reason'] = reason
            with self.assertRaises(ProviderOutputError) as caught:
                self.complete(packet)
            self.assertEqual(caught.exception.diagnostic, diagnostic)
            self.assertEqual(caught.exception.tokens, 30)

    def test_missing_invalid_usage_stays_unknown(self):
        for usage in (None, [], {}, {'total_tokens': True}, {'total_tokens': -1},
                      {'total_tokens': '30'}, {'prompt_tokens': 20, 'completion_tokens': 10}):
            with self.subTest(usage=usage):
                with self.assertRaises(ProviderOutputError) as caught:
                    self.complete(self.packet(usage=usage))
                self.assertIsNone(caught.exception.tokens)
                self.assertEqual(caught.exception.diagnostic, 'usage_missing')
        self.assertEqual(decode_response(json.dumps(self.packet(usage={'total_tokens': 0})))[1], 0)

    def test_broken_envelope_preserves_usage_when_readable(self):
        for choices in (None, [], {}, [None], ['bad']):
            with self.assertRaises(ProviderOutputError) as caught:
                self.complete(self.packet(choices=choices))
            self.assertEqual(caught.exception.tokens, 30)
            self.assertEqual(caught.exception.diagnostic, 'envelope_invalid')
        for raw in (b'not JSON', b'[]', b'null', b'\xff', b'{"usage":1,"usage":2}'):
            with self.assertRaises(ProviderOutputError) as caught:
                self.complete(raw)
            self.assertIsNone(caught.exception.tokens)
            self.assertEqual(caught.exception.diagnostic, 'envelope_invalid')

    def test_optional_metadata_validated(self):
        value, tokens, metadata = self.complete(self.packet(id='unsafe\nrequest', usage={
            'total_tokens': 30, 'prompt_tokens': True, 'completion_tokens': '10'}))
        self.assertEqual(tokens, 30)
        self.assertEqual(metadata, {'request_id': None, 'input_tokens': None, 'output_tokens': None})

    def test_oversize_is_unknown_and_never_retried(self):
        with self.assertRaises(ProviderOutputError) as caught:
            self.complete(b'x' * 1_000_001)
        self.assertEqual(caught.exception.diagnostic, 'response_too_large')
        self.assertIsNone(caught.exception.tokens)


if __name__ == '__main__':
    unittest.main()

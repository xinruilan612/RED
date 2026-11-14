"""Quote repair: whitespace, concatenation and unverifiable spans never abort a run."""
import unittest
from backend.citation_ids import fragments, locate, repair

SOURCE = {'source_id': 'web:1', 'text': '商品尺寸\n长度\n120 厘米\n深度\n80 厘米\n'
                                    '桌腿可在65-85cm之间调节\n享有10年品质保证。'}


def value(quote, source_id='web:1'):
    return {'core_gap': False, 'gaps': [], 'facts': [{'source_id': source_id, 'quote': quote}]}


class LocateTests(unittest.TestCase):
    def test_literal_and_outer_whitespace(self):
        self.assertEqual(locate(' 享有10年品质保证。 ', SOURCE['text']), '享有10年品质保证。')

    def test_whitespace_insensitive_returns_source_characters(self):
        span = locate('长度 120 厘米', SOURCE['text'])
        self.assertEqual(span, '长度\n120 厘米')  # source's own newline preserved
        self.assertIn(span, SOURCE['text'])

    def test_missing_returns_none(self):
        self.assertIsNone(locate('完全不存在的句子', SOURCE['text']))

    def test_fragments_split_on_line_breaks_only(self):
        # Sentence boundaries are NOT split points: they overlap with the audience
        # ellipsis expansion and with legitimate multi-clause quotes.
        self.assertEqual(fragments('A\nB。C'), ['A', 'B。C'])
        self.assertEqual(fragments('长度 120 厘米\n深度 80 厘米'), ['长度 120 厘米', '深度 80 厘米'])


class RepairTests(unittest.TestCase):
    def test_concatenated_quote_becomes_verified_spans(self):
        quote = '长度 120 厘米\n深度 80 厘米\n享有10年品质保证。\n完全不存在的句子'
        out, repairs = repair('research', value(quote), [SOURCE])
        self.assertEqual(len(out['facts']), 3)
        for fact in out['facts']:
            self.assertIn(fact['quote'], SOURCE['text'])
        self.assertEqual(repairs[0]['reason'], 'quote_split_into_fragments')
        self.assertEqual(repairs[0]['unmatched'], 1)

    def test_whitespace_only_mismatch_is_repaired_not_split(self):
        out, repairs = repair('research', value('长度 120 厘米'), [SOURCE])
        self.assertEqual(len(out['facts']), 1)
        self.assertIn(out['facts'][0]['quote'], SOURCE['text'])
        self.assertEqual(repairs[0]['reason'], 'quote_whitespace_normalized')

    def test_unverifiable_quote_is_left_for_the_strict_verifier(self):
        # We must not delete it (silently passing) nor rewrite it (inventing a
        # citation): keep it untouched so verify_quotes still rejects the output.
        payload = value('这句话原文里没有')
        out, repairs = repair('research', payload, [SOURCE])
        self.assertEqual(out['facts'], payload['facts'])
        self.assertEqual(repairs, [])

    def test_verified_quote_is_untouched(self):
        out, repairs = repair('research', value('享有10年品质保证。'), [SOURCE])
        self.assertEqual(out['facts'][0]['quote'], '享有10年品质保证。')
        self.assertEqual(repairs, [])

    def test_stage_without_quote_field_is_returned_unchanged(self):
        payload = {'candidates': ['x']}
        out, repairs = repair('title', payload, [SOURCE])
        self.assertEqual(out, payload)
        self.assertEqual(repairs, [])


NEAR_SOURCE = {'source_id': 'web:2',
               'text': '想象一下，疲惫一天后回到家中，只需轻松一按，就能享受清洁的地面，再也不用为清理打扫烦恼。'}


class NearCopyTests(unittest.TestCase):
    def test_one_character_slip_is_repaired_to_source_characters(self):
        quote = '想象一下，疲惫一天后回到家里，只需轻松一按，就能享受清洁的地面'
        out, repairs = repair('audience', {'observations': [
            {'source_id': 'web:2', 'quote': quote, 'interpretation': '观察'}]}, [NEAR_SOURCE])
        self.assertIn(out['observations'][0]['quote'], NEAR_SOURCE['text'])
        self.assertEqual(out['observations'][0]['interpretation'], '观察')
        self.assertEqual(repairs[0]['reason'], 'quote_near_match')

    def test_changed_number_is_never_repaired(self):
        quote = '长度至少120厘米，深度至少46厘米'
        source = {'source_id': 'web:3', 'text': '长度至少120厘米，深度至少47厘米。'}
        out, repairs = repair('research', {'facts': [{'source_id': 'web:3', 'quote': quote}]}, [source])
        self.assertEqual(out['facts'], [{'source_id': 'web:3', 'quote': quote}])
        self.assertEqual(repairs, [])

    def test_drop_unmatched_records_gap_and_keeps_the_rest(self):
        payload = {'observations': [
            {'source_id': 'web:2', 'quote': '完全无关的一句，原文里没有'},
            {'source_id': 'web:2', 'quote': '只需轻松一按'}]}
        out, repairs = repair('audience', payload, [NEAR_SOURCE], drop_unmatched=True)
        self.assertEqual(len(out['observations']), 1)
        self.assertEqual(out['observations'][0]['quote'], '只需轻松一按')
        self.assertEqual(repairs[0]['reason'], 'quote_unverifiable_dropped')

    def test_review_never_drops_or_near_matches_claims(self):
        raw = {'decision': 'approved', 'claim_map': [
            {'source_id': 'web:2', 'quote': '想象一下，疲惫一天后回到家中，只需轻松一按'}]}
        out, repairs = repair('review', raw, [NEAR_SOURCE], drop_unmatched=True)
        self.assertEqual(out['claim_map'], raw['claim_map'])
        self.assertEqual(repairs, [])


if __name__ == '__main__':
    unittest.main()

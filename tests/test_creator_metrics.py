import copy
import unittest
from datetime import date

from backend.creator_metrics import CreatorMetricsError, exact_metric, parse_creator_metrics


def fixture():
    return {'source_id': '0123456789abcdef01234567', 'creator_account_id': '7498706327',
            'home': {'account_label': '小红书账号: 7498706327', 'period': '统计周期 10-03 至 10-09',
                     'period_days': 7, 'blocks': [{'label': '曝光数', 'value': '25', 'unit': ''},
                                               {'label': '封面点击率', 'value': '12.5', 'unit': '%'},
                                               {'label': '观看数', 'value': '1.2万', 'unit': ''}]},
            'notes': [{'id': 'note-1', 'title': '我的笔记', 'time': '2026-10-02 12:30',
                       'stats': [{'kind': kind, 'value': str(value)} for kind, value in
                                 [('shares', 0), ('views', 24), ('likes', 3), ('favorites', 1), ('comments', 2)]]}]}


def parse(payload=None, **kwargs):
    options = {'source_id': '0123456789abcdef01234567', 'creator_account_id': '7498706327',
               'observed_at': '2026-10-10T09:00:00+08:00', 'today': date(2026, 10, 10)}
    options.update(kwargs)
    return parse_creator_metrics(payload if payload is not None else fixture(), **options)


class CreatorMetricsTests(unittest.TestCase):
    def test_exact_numbers_and_abbreviations_are_distinct(self):
        for value, expected in [('0', 0), ('123', 123), ('1,234', 1234), ('1.2万', None),
                                ('24+', None), ('--', None), ('1.0', None), ('-1', None),
                                ('1,2', None), ('１２', None), (True, None), ('1000000000001', None)]:
            with self.subTest(value=value):
                self.assertEqual(exact_metric(value), expected)
        for value, expected in [('12.3%', 12.3), ('100%', 100), ('0%', 0), ('101%', None),
                                ('12.3', None), ('NaN%', None), ('-1%', None)]:
            with self.subTest(value=value):
                self.assertEqual(exact_metric(value, percentage=True), expected)

    def test_net_followers_allow_exact_negative_counts_only(self):
        packet = fixture()
        packet['home']['blocks'] = [{'label': '净涨粉', 'value': '-2', 'unit': ''},
                                   {'label': '取消关注', 'value': '3', 'unit': ''}]
        result = parse(packet)
        self.assertEqual(result['account']['metrics']['followers_gained'], -2)
        self.assertEqual(result['account']['metrics']['unfollows'], 3)
        self.assertEqual(exact_metric('-1,234', signed=True), -1234)
        self.assertIsNone(exact_metric('-1.2万', signed=True))
        self.assertIsNone(exact_metric('-2'))
        with self.assertRaises(CreatorMetricsError):
            parse(source_id='not-canonical')

    def test_contract_keeps_scope_raw_display_and_unknowns(self):
        packet = fixture(); original = copy.deepcopy(packet); result = parse(packet)
        self.assertEqual(packet, original)
        self.assertEqual(result['status'], 'synced')
        self.assertFalse(result['official_api'])
        self.assertIsNone(result['source_updated_at'])
        self.assertEqual(result['observed_at'], '2026-10-10T01:00:00+00:00')
        account = result['account']
        self.assertEqual((account['period_start'], account['period_end']), ('2026-10-03', '2026-10-09'))
        self.assertEqual(account['period_display'], '统计周期 10-03 至 10-09')
        self.assertEqual(account['metrics']['exposure'], 25)
        self.assertEqual(account['metrics']['cover_ctr'], 12.5)
        self.assertIsNone(account['metrics']['views'])
        self.assertEqual(account['metric_displays']['views'], '1.2万')
        self.assertIsNone(account['metrics']['profile_visitors'])
        note = result['notes'][0]
        self.assertEqual(note['metrics'], {'exposure': None, 'shares': 0, 'views': 24, 'likes': 3, 'favorites': 1, 'comments': 2})
        self.assertEqual(note['source_url'], 'https://www.xiaohongshu.com/explore/note-1')
        self.assertEqual(note['published_display'], packet['notes'][0]['time'])

    def test_both_bound_identifiers_and_visible_account_must_match(self):
        for key in ['source_id', 'creator_account_id', 'account_label']:
            packet = fixture()
            if key == 'account_label':
                packet['home'][key] = '小红书账号: 123456'
            else:
                packet[key] = 'other'
            with self.subTest(key=key), self.assertRaises(CreatorMetricsError):
                parse(packet)

    def test_unverified_duplicate_and_missing_note_columns_fail_closed(self):
        for change in ['unknown', 'duplicate', 'missing', 'positional']:
            packet = fixture(); stats = packet['notes'][0]['stats']
            if change == 'unknown': stats[0]['kind'] = 'new_icon'
            elif change == 'duplicate': stats[0]['kind'] = stats[1]['kind']
            elif change == 'missing': stats.pop()
            else: stats[0].pop('kind')
            with self.subTest(change=change), self.assertRaises(CreatorMetricsError):
                parse(packet)

    def test_unknown_home_labels_duplicates_and_invalid_note_ids_rejected(self):
        for change in ['unknown', 'duplicate', 'id', 'duplicate_note']:
            packet = fixture()
            if change == 'unknown': packet['home']['blocks'][0]['label'] = '新版未知指标'
            elif change == 'duplicate': packet['home']['blocks'].append(packet['home']['blocks'][0])
            elif change == 'id': packet['notes'][0]['id'] = '../../other'
            else: packet['notes'].append(packet['notes'][0])
            with self.subTest(change=change), self.assertRaises(CreatorMetricsError): parse(packet)

    def test_year_boundary_inference_is_validated(self):
        packet = fixture(); packet['home']['period'] = '统计周期 12-29 至 01-04'
        result = parse(packet, today=date(2027, 1, 5), observed_at='2027-01-05T00:00:00+08:00')
        self.assertEqual(result['account']['period_start'], '2026-12-29')
        self.assertEqual(result['account']['period_end'], '2027-01-04')
        packet['home']['period'] = '统计周期 12-25 至 12-31'
        result = parse(packet, today=date(2027, 1, 1), observed_at='2027-01-01T00:00:00+08:00')
        self.assertEqual(result['account']['period_end'], '2026-12-31')

    def test_future_invalid_and_inconsistent_periods_are_not_fabricated(self):
        for period in ['统计周期 10-05 至 10-11', '统计周期 02-30 至 03-06',
                       '统计周期 10-02 至 10-09', '10-03 至 10-09']:
            packet = fixture(); packet['home']['period'] = period
            with self.subTest(period=period), self.assertRaises(CreatorMetricsError): parse(packet)

    def test_timezone_required_and_future_observation_rejected(self):
        for observed in ['2026-10-10T00:00:00', 'invalid', '2026-10-11T01:00:00+08:00']:
            with self.subTest(observed=observed), self.assertRaises(CreatorMetricsError): parse(observed_at=observed)


if __name__ == '__main__':
    unittest.main()

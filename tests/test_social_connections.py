import copy
import unittest

from backend.accounts import new_account
from backend.contracts import DomainError
from backend.social_connections import SocialConnections, capabilities, data_center


class SocialConnectionsTests(unittest.TestCase):
    def setUp(self):
        self.state = dict(accounts=[new_account('mine', '个人账号', 'xiaohongshu')],
                          publications=[], metrics=[])

    def add_metric(self, identity='mine', source='manual', stamp='2026-10-01T12:00:00+08:00'):
        number = str(len(self.state['metrics']))
        self.state['publications'].append(dict(id='p'+number, account_id=identity,
            platform='xiaohongshu', provenance=source))
        self.state['metrics'].append(dict(id='m'+number, publication_id='p'+number,
            account_id=identity, platform='xiaohongshu', source_type=source,
            observed_at=stamp, window='24h', values={'likes': 0}))

    def test_profile_and_claimed_connection_cannot_enable_sync(self):
        self.state['accounts'][0].update(connected=True, adapter='fake', api_key='secret')
        self.state['connections'] = [{'status': 'connected'}]
        value = data_center(self.state, 'mine')
        self.assertFalse(value['connection_available'])
        self.assertFalse(value['automatic_sync_available'])
        self.assertEqual(value['connection_status'], 'not_connected')
        self.assertIsNone(value['last_sync_at'])
        self.assertNotIn('secret', str(value))

    def test_manual_data_simulation_and_other_account_are_separate(self):
        self.add_metric()
        self.add_metric(source='simulation')
        self.add_metric(identity='other')
        original = copy.deepcopy(self.state)
        value = data_center(self.state, 'mine')['local_records']
        self.assertEqual(value['publication_count'], 1)
        self.assertEqual(value['metric_snapshot_count'], 1)
        self.assertEqual(value['latest_metric']['values']['likes'], 0)
        self.assertIsNone(value['latest_metric']['values']['views'])
        self.assertIsNone(value['comment_content_count'])
        self.assertFalse(value['latest_metric']['verified'])
        self.assertEqual(self.state, original)

    def test_latest_uses_instant_not_string_and_does_not_sum_snapshots(self):
        self.add_metric(stamp='2026-10-01T12:00:00+08:00')
        self.add_metric(stamp='2026-10-01T05:00:00+00:00')
        self.add_metric(stamp='invalid')
        self.state['metrics'][1]['values']['likes'] = 7
        value = data_center(self.state, 'mine')['local_records']
        self.assertEqual(value['latest_metric']['metric_id'], 'm1')
        self.assertEqual(value['latest_metric']['values']['likes'], 7)
        self.assertEqual(value['metric_snapshot_count'], 3)

    def test_foreign_publication_metric_and_wrong_platform_are_excluded(self):
        self.add_metric()
        self.state['metrics'][0]['publication_id'] = 'foreign'
        self.add_metric()
        self.state['metrics'][1]['platform'] = 'douyin'
        self.assertEqual(data_center(self.state, 'mine')['local_records']['metric_snapshot_count'], 0)

    def test_unknown_account_and_owner_cannot_read_profile(self):
        class Operations:
            def read(inner, owner):
                return self.state if owner == 'owner' else dict(accounts=[])
        service = SocialConnections(Operations())
        self.assertEqual(service.read('owner', 'mine')['account_id'], 'mine')
        with self.assertRaises(DomainError):
            service.read('other', 'mine')
        with self.assertRaises(DomainError):
            service.read('owner', 'unknown')

    def test_capabilities_copy_and_unreviewed_platform(self):
        value = capabilities()
        value['sources'][0]['url'] = 'changed'
        self.assertNotEqual(capabilities()['sources'][0]['url'], 'changed')
        self.assertEqual(capabilities('douyin')['status'], 'not_implemented')
        self.assertEqual(capabilities('douyin')['sources'], [])
        with self.assertRaises(DomainError):
            capabilities('unknown')


if __name__ == '__main__':
    unittest.main()

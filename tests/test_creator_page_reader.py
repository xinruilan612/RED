"""Regression coverage for reading one stable period without clicking controls."""
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from scripts.xhs_creator_reader import HOME, ReaderStopped, home_data


class CreatorPageTests(unittest.IsolatedAsyncioTestCase):
    def page(self, active='近7日', packets=None):
        body = SimpleNamespace(inner_text=AsyncMock(return_value='小红书账号: 123'))
        scope = SimpleNamespace(wait_for=AsyncMock())
        number = SimpleNamespace(first=SimpleNamespace(wait_for=AsyncMock()))
        tab = SimpleNamespace(inner_text=AsyncMock(return_value=active))
        elements = {'body':body,'.time-scope':scope,'.creator-block .number':number,'.d-segment-item.active':tab}
        return SimpleNamespace(url=HOME,goto=AsyncMock(),locator=lambda s:elements[s],
                               evaluate=AsyncMock(side_effect=packets or [{'views':3},{'views':3}]))

    async def test_snapshot_waits_until_period_and_metrics_are_stable(self):
        page = self.page(packets=[{'period':'old','views':80},{'period':'new','views':3},{'period':'new','views':3}])
        with patch('scripts.xhs_creator_reader.asyncio.sleep', new_callable=AsyncMock):
            result = await home_data(page, '123')
        self.assertEqual(result, {'period':'new','views':3})
        self.assertEqual(page.evaluate.await_count, 3)

    async def test_nondefault_period_is_rejected_without_switching(self):
        page = self.page(active='近30日')
        with self.assertRaisesRegex(ReaderStopped,'CREATOR_PERIOD_CHANGED'):
            await home_data(page, '123')
        page.evaluate.assert_not_awaited()

    async def test_different_creator_account_rejected_before_metrics(self):
        page = self.page()
        with self.assertRaisesRegex(ReaderStopped,'CREATOR_IDENTITY_CHANGED'):
            await home_data(page, '456')
        page.evaluate.assert_not_awaited()

    async def test_never_stable_metrics_are_not_returned(self):
        page = self.page(packets=[{'views':i} for i in range(6)])
        with patch('scripts.xhs_creator_reader.asyncio.sleep', new_callable=AsyncMock):
            with self.assertRaisesRegex(ReaderStopped,'CREATOR_DATA_UNSTABLE'):
                await home_data(page, '123')

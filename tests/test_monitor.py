import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock

from keel_telegram_bot.bot import KeelTelegramBot
from keel_telegram_bot.client.api_client import KeelApiClient
from keel_telegram_bot.db import Store
from keel_telegram_bot.monitoring.monitor import Monitor
from tests import TestBase
from tests.test_approval_messages import _approval


class MonitorTest(TestBase):

    def setUp(self):
        config = MagicMock()
        config.MONITOR_INTERVAL.value.total_seconds.return_value = 60
        config.TELEGRAM_CHAT_IDS.value = ["1", "2"]
        self.api = Mock(spec=KeelApiClient)
        self.bot = Mock(spec=KeelTelegramBot)
        self.bot.update_messages = AsyncMock()
        self.bot.on_new_pending_approval = AsyncMock(return_value=True)
        self.store = Store()
        self.monitor = Monitor(config, self.api, self.bot, self.store)

    def _run(self):
        asyncio.run(self.monitor._run())

    def test_first_run_with_new_database_does_not_announce_pending_approvals(self):
        self.api.get_approvals.return_value = [_approval("a1")]
        self._run()
        self.bot.on_new_pending_approval.assert_not_called()
        self.assertTrue(self.store.is_announced("a1", 1))

    def test_approval_that_appeared_while_the_bot_was_down_is_announced(self):
        self.api.get_approvals.return_value = [_approval("a1")]
        self._run()

        # restart: a new Monitor on the same database, and a new approval showed up in the meantime
        self.api.get_approvals.return_value = [_approval("a1"), _approval("a2")]
        self._run()

        self.bot.on_new_pending_approval.assert_called()
        self.assertEqual(["a1", "a2"], [c.args[0].id for c in self.bot.on_new_pending_approval.call_args_list])

    def test_decided_approvals_are_forgotten(self):
        self.api.get_approvals.return_value = [_approval("a1")]
        self._run()
        self.api.get_approvals.return_value = []
        self._run()
        self.assertFalse(self.store.is_announced("a1", 1))

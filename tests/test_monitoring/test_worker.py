import unittest
from unittest.mock import Mock

from keel_telegram_bot.api_client import KeelApiClient
from keel_telegram_bot.bot import KeelTelegramBot
from keel_telegram_bot.monitoring.monitor import Monitor
from tests import TestBase


class WorkerTest(TestBase):

    @unittest.skip("doesn't work yet because of async context")
    def test_worker_job(self):
        # GIVEN
        config = self.config
        api_client = Mock(spec=KeelApiClient)
        bot = Mock(spec=KeelTelegramBot)
        worker = Monitor(
            config=config,
            api_client=api_client,
            bot=bot
        )

        # WHEN
        worker._worker_job()

        # THEN
        api_client.get_approvals.assert_called_once()

import asyncio
import os
import tempfile
from datetime import timedelta
from unittest.mock import Mock, AsyncMock, MagicMock, patch

from keel_telegram_bot.bot import KeelTelegramBot
from keel_telegram_bot.client.api_client import KeelApiClient
from keel_telegram_bot.helm.chart import HelmChart
from keel_telegram_bot.helm.checker import HelmChartUpdateChecker
from keel_telegram_bot.helm.client import HelmChartClient, InstallJobResult, InstallJobStatus
from keel_telegram_bot.helm.state import HelmChartState
from tests import TestBase


def _chart(name="loki", version="20.2.0"):
    return HelmChart(name=name, namespace="kube-system", chart=name, repo="https://x", version=version,
                     target_namespace=name)


def _config():
    config = MagicMock()
    config.TELEGRAM_BOT_TOKEN.value = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    config.TELEGRAM_CHAT_IDS.value = ["123"]
    config.TELEGRAM_ADMIN_USERNAMES.value = ["myadminuser"]
    config.TELEGRAM_FILTERS.value = []
    config.HELM_CHARTS_JOB_TIMEOUT.value = timedelta(minutes=1)
    return config


class HelmUpgradeResumeTest(TestBase):

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.state = HelmChartState(os.path.join(self._dir.name, "state.json"))
        self.client = Mock(spec=HelmChartClient)
        self.bot = KeelTelegramBot(_config(), Mock(spec=KeelApiClient), self.client,
                                   Mock(spec=HelmChartUpdateChecker), self.state)
        self.telegram = Mock()
        self.telegram.edit_message_reply_markup = AsyncMock()
        self._bot_property = type(self.bot).bot
        type(self.bot).bot = property(lambda _: self.telegram)

    def tearDown(self):
        type(self.bot).bot = self._bot_property
        self._dir.cleanup()

    @staticmethod
    def _buttons(call):
        return [b.text for row in call.kwargs["reply_markup"].inline_keyboard for b in row]

    def test_watch_reports_outcome_and_forgets_the_upgrade(self):
        self.state.add_pending_upgrade("loki", "20.3.0", 123, 7)
        self.client.wait_for_install_job.return_value = InstallJobResult(InstallJobStatus.SUCCEEDED, "done", None)

        with patch("keel_telegram_bot.bot.send_message", new=AsyncMock()):
            asyncio.run(self.bot._watch_helm_chart_upgrade(self.telegram, _chart(), "20.3.0", 123, 7))

        self.assertEqual(["Upgraded to 20.3.0"], self._buttons(self.telegram.edit_message_reply_markup.call_args))
        self.assertEqual([], self.state.pending_upgrades())

    def test_failed_watch_does_not_leave_the_upgrade_pending(self):
        self.state.add_pending_upgrade("loki", "20.3.0", 123, 7)
        self.client.wait_for_install_job.side_effect = RuntimeError("cluster unreachable")

        with patch("keel_telegram_bot.bot.send_message", new=AsyncMock()):
            asyncio.run(self.bot._watch_helm_chart_upgrade(self.telegram, _chart(), "20.3.0", 123, 7))

        self.assertEqual(["Upgrade to 20.3.0 unknown"],
                         self._buttons(self.telegram.edit_message_reply_markup.call_args))
        self.assertEqual([], self.state.pending_upgrades())

    def test_resume_watches_pending_upgrades(self):
        self.state.add_pending_upgrade("loki", "20.3.0", 123, 7)
        self.client.get_helm_chart.return_value = _chart()
        self.client.wait_for_install_job.return_value = InstallJobResult(InstallJobStatus.FAILED, "failed", "log")

        async def run():
            with patch("keel_telegram_bot.bot.send_message", new=AsyncMock()):
                await self.bot._resume_helm_chart_upgrades()
                await asyncio.gather(*list(self.bot._background_tasks))

        asyncio.run(run())

        self.assertEqual(["Upgrade to 20.3.0 failed"],
                         self._buttons(self.telegram.edit_message_reply_markup.call_args))
        self.assertEqual([], self.state.pending_upgrades())

    def test_resume_gives_up_on_unknown_chart(self):
        self.state.add_pending_upgrade("gone", "1.0.0", 123, 7)
        self.client.get_helm_chart.side_effect = KeyError("gone")

        asyncio.run(self.bot._resume_helm_chart_upgrades())

        self.assertEqual(["Upgrade to 1.0.0 unknown"],
                         self._buttons(self.telegram.edit_message_reply_markup.call_args))
        self.assertEqual([], self.state.pending_upgrades())
        self.client.wait_for_install_job.assert_not_called()

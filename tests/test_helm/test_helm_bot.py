import asyncio
import os
import tempfile
from unittest.mock import Mock, AsyncMock, MagicMock

from keel_telegram_bot.bot import KeelTelegramBot
from keel_telegram_bot.client.api_client import KeelApiClient
from keel_telegram_bot.helm.chart import HelmChart
from keel_telegram_bot.helm.checker import HelmChartCheckResult, HelmChartUpdateChecker
from keel_telegram_bot.helm.client import HelmChartClient
from keel_telegram_bot.helm.index import ChartVersion, find_update
from keel_telegram_bot.helm.state import HelmChartState
from keel_telegram_bot.helm.version import SemVer
from tests import TestBase


def _chart(name="loki", version="20.2.0"):
    return HelmChart(name=name, namespace="kube-system", chart=name, repo="https://x", version=version,
                     target_namespace=name)


def _result(chart: HelmChart, *versions: str) -> HelmChartCheckResult:
    available = [ChartVersion(version=x, semver=SemVer.parse(x)) for x in versions]
    return HelmChartCheckResult(chart=chart, update=find_update(chart.version, available))


def _config():
    # independent of any local config file
    config = MagicMock()
    config.TELEGRAM_BOT_TOKEN.value = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    config.TELEGRAM_CHAT_IDS.value = ["12345678"]
    config.TELEGRAM_ADMIN_USERNAMES.value = ["myadminuser"]
    config.TELEGRAM_FILTERS.value = []
    config.HELM_CHARTS_ALLOW.value = []
    config.HELM_CHARTS_DENY.value = []
    return config


class HelmBotTest(TestBase):

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.state = HelmChartState(os.path.join(self._dir.name, "state.json"))
        self.client = Mock(spec=HelmChartClient)
        self.bot = KeelTelegramBot(_config(), Mock(spec=KeelApiClient), self.client,
                                   Mock(spec=HelmChartUpdateChecker), self.state)
        self.bot.on_new_helm_chart_update = AsyncMock()

    def tearDown(self):
        self._dir.cleanup()

    def test_announce_once(self):
        results = [_result(_chart(), "20.3.0"), _result(_chart("alloy", "1.15.0"))]

        notified = asyncio.run(self.bot.on_helm_chart_check_results(results))
        self.assertEqual(["loki"], [x.chart.name for x in notified])

        notified = asyncio.run(self.bot.on_helm_chart_check_results(results))
        self.assertEqual([], notified)

        notified = asyncio.run(self.bot.on_helm_chart_check_results(results, force=True))
        self.assertEqual(["loki"], [x.chart.name for x in notified])
        self.assertEqual(2, self.bot.on_new_helm_chart_update.call_count)

    def test_ignored_not_announced(self):
        self.state.ignore("loki", ["20.3.0"])
        results = [_result(_chart(), "20.3.0")]

        self.assertEqual([], asyncio.run(self.bot.on_helm_chart_check_results(results)))
        self.assertEqual([], asyncio.run(self.bot.on_helm_chart_check_results(results, force=True)))

        # a newer version is announced again
        results = [_result(_chart(), "20.3.0", "20.4.0")]
        self.assertEqual(1, len(asyncio.run(self.bot.on_helm_chart_check_results(results))))

    def test_menu(self):
        def button_data(result):
            menu = self.bot.create_helm_chart_update_menu(result.update)
            return {x[0].text: x[0].callback_data for x in menu.inline_keyboard}

        self.assertEqual({"Upgrade": "hu:20.3.0", "Ignore": "hi:20.3.0"},
                         button_data(_result(_chart(), "20.3.0")))
        # major update: no upgrade to the new major, but to the newest version within the current major
        self.assertEqual({"Upgrade to 20.3.0": "hu:20.3.0", "Ignore": "hi:21.0.0,20.3.0"},
                         button_data(_result(_chart(), "20.3.0", "21.0.0")))
        self.assertEqual({"Ignore": "hi:21.0.0"},
                         button_data(_result(_chart(), "21.0.0")))

    def _click(self, data: str, username="myadminuser", chat_id=12345678):
        update = MagicMock()
        update.callback_query.data = data
        update.callback_query.from_user.username = username
        update.effective_chat.id = chat_id
        update.effective_message.text = "New helm chart version: loki\nRelease: loki\nNamespace: loki"
        update.effective_message.edit_reply_markup = AsyncMock()
        context = MagicMock()
        context.bot.answer_callback_query = AsyncMock()
        asyncio.run(self.bot._inline_keyboard_click_callback(update, context))
        return update, context

    def test_upgrade(self):
        self.client.get_helm_chart.return_value = _chart()

        update, context = self._click("hu:20.3.0")

        self.client.set_version.assert_called_once_with("loki", "20.3.0")
        context.application.create_task.assert_called_once()
        context.application.create_task.call_args[0][0].close()
        update.effective_message.edit_reply_markup.assert_called_once()

    def test_upgrade_major_refused(self):
        self.client.get_helm_chart.return_value = _chart()

        _, context = self._click("hu:21.0.0")

        self.client.set_version.assert_not_called()
        self.assertIn("Major", context.bot.answer_callback_query.call_args.kwargs["text"])

    def test_upgrade_already_done(self):
        self.client.get_helm_chart.return_value = _chart(version="20.3.0")

        self._click("hu:20.3.0")

        self.client.set_version.assert_not_called()

    def test_ignore(self):
        self.client.get_helm_chart.return_value = _chart()

        update, _ = self._click("hi:21.0.0,20.3.0")

        self.assertTrue(self.state.is_ignored("loki", "21.0.0"))
        self.assertTrue(self.state.is_ignored("loki", "20.3.0"))
        update.effective_message.edit_reply_markup.assert_called_once()

    def test_unauthorized(self):
        for kwargs in [{"username": "someoneelse"}, {"chat_id": 999}]:
            _, context = self._click("hu:20.3.0", **kwargs)
            self.assertIn("not allowed", context.bot.answer_callback_query.call_args.kwargs["text"])
        self.client.get_helm_chart.assert_not_called()
        self.client.set_version.assert_not_called()

import asyncio
import os
import tempfile
from datetime import timedelta
from unittest.mock import Mock, AsyncMock, MagicMock, patch

from keel_telegram_bot.bot import KeelTelegramBot
from keel_telegram_bot.client.api_client import KeelApiClient
from keel_telegram_bot.db import Store
from keel_telegram_bot.helm.chart import HelmChart
from keel_telegram_bot.helm.checker import HelmChartCheckResult, HelmChartUpdateChecker
from keel_telegram_bot.helm.client import HelmChartClient, InstallJobResult, InstallJobStatus
from keel_telegram_bot.helm.index import ChartVersion, find_update
from keel_telegram_bot.helm.state import HelmChartState
from keel_telegram_bot.helm.version import SemVer
from keel_telegram_bot.monitoring.helm_chart_monitor import HelmChartMonitor
from tests import TestBase

CHAT_ID = 12345678
MESSAGE_ID = 7


def _chart(name="loki", version="20.2.0", chart=None, values_content=None):
    return HelmChart(name=name, namespace="kube-system", chart=chart or name, repo="https://x", version=version,
                     target_namespace=name, values_content=values_content)


def _result(chart: HelmChart, *versions: str) -> HelmChartCheckResult:
    available = [ChartVersion(version=x, semver=SemVer.parse(x)) for x in versions]
    return HelmChartCheckResult(chart=chart, update=find_update(chart.version, available))


def _config(auto_upgrade):
    # independent of any local config file
    config = MagicMock()
    config.TELEGRAM_BOT_TOKEN.value = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    config.TELEGRAM_CHAT_IDS.value = [str(CHAT_ID)]
    config.TELEGRAM_ADMIN_USERNAMES.value = ["myadminuser"]
    config.TELEGRAM_FILTERS.value = []
    config.HELM_CHARTS_ALLOW.value = []
    config.HELM_CHARTS_DENY.value = []
    config.HELM_CHARTS_NOTIFY_ONLY.value = []
    config.HELM_CHARTS_AUTO_UPGRADE.value = auto_upgrade
    config.HELM_CHARTS_AUTO_UPGRADE_EXCLUDE.value = []
    config.HELM_CHARTS_JOB_TIMEOUT.value = timedelta(minutes=1)
    return config


class HelmAutoUpgradeTest(TestBase):

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.store = Store()
        self.state = HelmChartState(os.path.join(self._dir.name, "state.json"))
        self.client = Mock(spec=HelmChartClient)
        self.client.wait_for_install_job.return_value = InstallJobResult(InstallJobStatus.SUCCEEDED, "done", None)
        self.bot = KeelTelegramBot(_config(["minor", "patch"]), Mock(spec=KeelApiClient), self.client,
                                   Mock(spec=HelmChartUpdateChecker), self.state, self.store)
        self.bot.on_new_helm_chart_update = AsyncMock()
        self.telegram = Mock()
        self.telegram.edit_message_reply_markup = AsyncMock()
        self._bot_property = type(self.bot).bot
        type(self.bot).bot = property(lambda _: self.telegram)

        sent = Mock()
        sent.chat_id = CHAT_ID
        sent.message_id = MESSAGE_ID
        self.send_message = AsyncMock(return_value=sent)

    def tearDown(self):
        type(self.bot).bot = self._bot_property
        self._dir.cleanup()

    def _set_auto_upgrade(self, levels):
        self.bot._config.HELM_CHARTS_AUTO_UPGRADE.value = levels

    def _check(self, *results: HelmChartCheckResult):
        async def run():
            with patch("keel_telegram_bot.bot.send_message", new=self.send_message):
                notified = await self.bot.on_helm_chart_check_results(list(results))
                await asyncio.gather(*list(self.bot._background_tasks))
                return notified

        return asyncio.run(run())

    def _texts(self):
        return [call.args[2] for call in self.send_message.call_args_list]

    def _announced(self):
        """
        :return: (chart version, offered versions) of each announcement with buttons
        """
        return [(call.args[0].version, call.args[1].offered_versions)
                for call in self.bot.on_new_helm_chart_update.call_args_list]

    def _assert_not_upgraded(self):
        self.client.set_version.assert_not_called()
        self.assertEqual([], self._texts())

    def test_disabled_by_default(self):
        self._set_auto_upgrade([])

        notified = self._check(_result(_chart(), "20.2.1", "20.3.0"))

        self._assert_not_upgraded()
        self.assertEqual(["loki"], [x.chart.name for x in notified])
        self.assertEqual([("20.2.0", ["20.3.0"])], self._announced())

    def test_minor(self):
        notified = self._check(_result(_chart(), "20.2.1", "20.3.0"))

        self.client.set_version.assert_called_once_with("loki", "20.3.0")
        self.assertEqual(["loki"], [x.chart.name for x in notified])
        self.assertEqual([], self._announced())
        notification, report = self._texts()
        self.assertIn("Automatic helm chart upgrade: loki", notification)
        self.assertIn("Version: 20.2.0 -&gt; 20.3.0", notification)
        self.assertIn("Upgraded loki to 20.3.0", report)
        self.assertEqual(MESSAGE_ID, self.send_message.call_args_list[1].kwargs["reply_to"])
        self.assertEqual([], self.store.pending_upgrades())
        self.assertFalse(self.state.is_failed("loki", "20.3.0"))

    def test_patch_only(self):
        self._set_auto_upgrade(["patch"])

        self._check(_result(_chart(), "20.2.1", "20.2.2", "20.3.0"))

        # the newest patch version is installed, the minor update is announced relative to it
        self.client.set_version.assert_called_once_with("loki", "20.2.2")
        self.assertEqual([("20.2.2", ["20.3.0"])], self._announced())

    def test_patch_only_without_patch_update(self):
        self._set_auto_upgrade(["patch"])

        self._check(_result(_chart(), "20.3.0"))

        self._assert_not_upgraded()
        self.assertEqual([("20.2.0", ["20.3.0"])], self._announced())

    def test_minor_only_without_minor_update(self):
        self._set_auto_upgrade(["minor"])

        self._check(_result(_chart(), "20.2.1"))

        self._assert_not_upgraded()
        self.assertEqual([("20.2.0", ["20.2.1"])], self._announced())

    def test_major_is_only_announced(self):
        self._check(_result(_chart(), "21.0.0"))

        self._assert_not_upgraded()
        self.assertEqual([("20.2.0", ["21.0.0"])], self._announced())

    def test_within_major_upgraded_and_major_announced(self):
        self._check(_result(_chart(), "20.3.0", "21.0.0"))

        self.client.set_version.assert_called_once_with("loki", "20.3.0")
        self.assertEqual([("20.3.0", ["21.0.0"])], self._announced())

    def test_prerelease_not_upgraded(self):
        self._check(_result(_chart(version="20.3.0-rc.1"), "20.3.0-rc.2"))

        self._assert_not_upgraded()
        self.assertEqual([("20.3.0-rc.1", ["20.3.0-rc.2"])], self._announced())

    def test_notify_only_not_upgraded(self):
        self.bot._config.HELM_CHARTS_NOTIFY_ONLY.value = ["loki"]

        self._check(_result(_chart(), "20.3.0"))

        self._assert_not_upgraded()
        self.assertEqual(1, len(self._announced()))

    def test_unupgradeable_crds_not_upgraded(self):
        chart = _chart("prometheus", "80.0.0", chart="kube-prometheus-stack")

        self._check(_result(chart, "80.1.0"))
        self._assert_not_upgraded()

        chart = _chart("prometheus", "80.0.0", chart="kube-prometheus-stack",
                       values_content="crds:\n  upgradeJob:\n    enabled: true\n")
        self._check(_result(chart, "80.1.0"))
        self.client.set_version.assert_called_once_with("prometheus", "80.1.0")

    def test_excluded_not_upgraded(self):
        self.bot._config.HELM_CHARTS_AUTO_UPGRADE_EXCLUDE.value = ["loki"]

        self._check(_result(_chart(), "20.3.0"), _result(_chart("alloy", "1.0.0"), "1.0.1"))

        self.client.set_version.assert_called_once_with("alloy", "1.0.1")
        self.assertEqual([("20.2.0", ["20.3.0"])], self._announced())

    def test_filtered_for_all_chats_not_upgraded(self):
        self.bot._config.TELEGRAM_FILTERS.value = [{"chat_id": str(CHAT_ID), "identifier": "^helmchart/other/"}]

        self._check(_result(_chart(), "20.3.0"))

        self.client.set_version.assert_not_called()

    def test_running_upgrade_not_started_again(self):
        self.store.add_pending_upgrade("loki", "20.3.0", CHAT_ID, 3)

        self._check(_result(_chart(), "20.3.0"))

        self.client.set_version.assert_not_called()

    def test_ignored_not_upgraded(self):
        self.state.ignore("loki", ["20.3.0"])

        self._check(_result(_chart(), "20.3.0"))

        self._assert_not_upgraded()
        self.assertEqual([], self._announced())

    def test_failed_upgrade_falls_back_to_announcement(self):
        self.client.wait_for_install_job.return_value = InstallJobResult(
            InstallJobStatus.FAILED, "Job kube-system/helm-install-loki failed", "Error: UPGRADE FAILED")

        self._check(_result(_chart(), "20.3.0"))

        report = self._texts()[-1]
        self.assertIn("Upgrade of loki to 20.3.0 failed", report)
        self.assertIn("Error: UPGRADE FAILED", report)
        self.assertTrue(self.state.is_failed("loki", "20.3.0"))

        # the HelmChart stays at the failed version, nothing is retried
        self.client.set_version.reset_mock()
        self._check(_result(_chart(version="20.3.0"), "20.3.0"))
        self.client.set_version.assert_not_called()

        # after a reset to the old version, the failed version is announced with buttons instead
        self._check(_result(_chart(), "20.3.0"))
        self.client.set_version.assert_not_called()
        self.assertEqual([("20.2.0", ["20.3.0"])], self._announced())

        # a newer version is upgraded automatically again
        self._check(_result(_chart(), "20.3.0", "20.3.1"))
        self.client.set_version.assert_called_once_with("loki", "20.3.1")

    def test_timeout_counts_as_failure(self):
        self.client.wait_for_install_job.return_value = InstallJobResult(InstallJobStatus.TIMEOUT, "timeout", None)

        self._check(_result(_chart(), "20.3.0"))

        self.assertTrue(self.state.is_failed("loki", "20.3.0"))

    def test_set_version_error_falls_back_to_announcement(self):
        self.client.set_version.side_effect = RuntimeError("forbidden")

        notified = self._check(_result(_chart(), "20.3.0"))

        self.assertEqual(["loki"], [x.chart.name for x in notified])
        self.assertIn("Automatic upgrade of loki to 20.3.0 failed: forbidden", self._texts()[0])
        self.assertEqual([("20.2.0", ["20.3.0"])], self._announced())
        self.assertTrue(self.state.is_failed("loki", "20.3.0"))
        self.client.wait_for_install_job.assert_not_called()

    def test_running_upgrade_is_stored(self):
        async def run():
            with patch("keel_telegram_bot.bot.send_message", new=self.send_message):
                await self.bot.on_helm_chart_check_results([_result(_chart(), "20.3.0")])
                pending = self.store.pending_upgrades()
                await asyncio.gather(*list(self.bot._background_tasks))
                return pending

        pending = asyncio.run(run())

        self.assertEqual([("loki", "20.3.0", CHAT_ID, MESSAGE_ID)],
                         [(x.name, x.version, x.chat_id, x.message_id) for x in pending])
        self.assertEqual([], self.store.pending_upgrades())

    def test_resume_watches_the_job_once_for_all_chats(self):
        self.store.add_pending_upgrade("loki", "20.3.0", 1, 10)
        self.store.add_pending_upgrade("loki", "20.3.0", 2, 20)
        self.client.get_helm_chart.return_value = _chart(version="20.3.0")

        async def run():
            with patch("keel_telegram_bot.bot.send_message", new=self.send_message):
                await self.bot._resume_helm_chart_upgrades()
                await asyncio.gather(*list(self.bot._background_tasks))

        asyncio.run(run())

        self.client.wait_for_install_job.assert_called_once()
        self.assertEqual({1, 2}, {call.args[1] for call in self.send_message.call_args_list})
        self.assertEqual([], self.store.pending_upgrades())

    def test_monitor_reports_automatic_upgrade(self):
        # the watcher of the upgrade has to finish after the check that started it, or the upgrade stays pending:
        # no report in Telegram, and approvals of Keel's own workload stay deferred
        config = MagicMock()
        config.HELM_CHARTS_INTERVAL.value = timedelta(hours=24)
        checker = Mock(spec=HelmChartUpdateChecker)
        checker.check.return_value = [_result(_chart(), "20.2.1", "20.3.0")]
        monitor = HelmChartMonitor(config, checker, self.bot)

        async def run():
            with patch("keel_telegram_bot.bot.send_message", new=self.send_message):
                task = asyncio.create_task(monitor.start())
                deadline = asyncio.get_running_loop().time() + 5
                while len(self._texts()) < 2 or len(self.store.pending_upgrades()) > 0:
                    self.assertLess(asyncio.get_running_loop().time(), deadline, "upgrade was not reported")
                    await asyncio.sleep(0.01)
                monitor.stop()
                await asyncio.wait_for(task, timeout=5)

        asyncio.run(run())

        self.client.set_version.assert_called_once_with("loki", "20.3.0")
        notification, report = self._texts()
        self.assertIn("Upgraded loki to 20.3.0", report)
        self.assertEqual(MESSAGE_ID, self.send_message.call_args_list[1].kwargs["reply_to"])


class HelmAutoUpgradeConfigTest(TestBase):

    def test_levels(self):
        entry = self.config.HELM_CHARTS_AUTO_UPGRADE
        self.assertEqual([], entry.value)
        try:
            entry.value = ["minor", "patch"]
            self.assertEqual(["minor", "patch"], entry.value)
            for invalid in (["major"], ["minor", "major"], ["Minor"], ["all"]):
                with self.assertRaises(ValueError):
                    entry.value = invalid
        finally:
            entry.value = []

import logging

from keel_telegram_bot.bot import KeelTelegramBot
from keel_telegram_bot.config import Config
from keel_telegram_bot.helm.checker import HelmChartUpdateChecker
from keel_telegram_bot.monitoring import RegularIntervalWorker
from keel_telegram_bot.stats import HELM_CHART_WATCHER_TIME

LOGGER = logging.getLogger(__name__)


class HelmChartMonitor(RegularIntervalWorker):
    """
    Regularly checks HelmChart objects for new chart versions
    """

    def __init__(self, config: Config, checker: HelmChartUpdateChecker, bot: KeelTelegramBot):
        interval_seconds = config.HELM_CHARTS_INTERVAL.value.total_seconds()
        super().__init__(interval_seconds)
        self._config = config
        self._checker = checker
        self._bot = bot

    @HELM_CHART_WATCHER_TIME.time()
    async def _run(self):
        """
        Called repeatedly
        """
        results = self._checker.check()
        notified = await self._bot.on_helm_chart_check_results(results)
        LOGGER.debug(f"Checked {len(results)} HelmChart(s), sent {len(notified)} update notification(s)")

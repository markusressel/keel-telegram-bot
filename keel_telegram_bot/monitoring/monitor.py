import logging

from keel_telegram_bot.bot import KeelTelegramBot
from keel_telegram_bot.client.api_client import KeelApiClient
from keel_telegram_bot.config import Config
from keel_telegram_bot.monitoring import RegularIntervalWorker
from keel_telegram_bot.stats import APPROVAL_WATCHER_TIME, NEW_PENDING_APPROVAL_COUNTER
from keel_telegram_bot.util import filter_new_by_key

LOGGER = logging.getLogger(__name__)


class Monitor(RegularIntervalWorker):

    def __init__(self, config: Config, api_client: KeelApiClient, bot: KeelTelegramBot):
        interval_seconds = config.MONITOR_INTERVAL.value.total_seconds()
        super().__init__(interval_seconds)
        self._config = config
        self._api_client = api_client
        self._bot = bot
        self._old = None

    @APPROVAL_WATCHER_TIME.time()
    async def _run(self):
        """
        Called repeatedly
        """
        active = self._api_client.get_approvals(rejected=False, archived=False)

        try:
            # update existing messages
            await self._bot.update_messages()
        except Exception as ex:
            LOGGER.exception(ex)

        if self._old is None:
            self._old = active
            return

        new_pending = filter_new_by_key(self._old, active, key=lambda x: x.id)
        self._old = active

        for item in new_pending:
            NEW_PENDING_APPROVAL_COUNTER.inc()
            await self._bot.on_new_pending_approval(item)

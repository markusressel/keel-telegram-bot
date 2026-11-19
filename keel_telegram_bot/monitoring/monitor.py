import logging

from keel_telegram_bot.bot import KeelTelegramBot
from keel_telegram_bot.client.api_client import KeelApiClient
from keel_telegram_bot.config import Config
from keel_telegram_bot.db import Store
from keel_telegram_bot.monitoring import RegularIntervalWorker
from keel_telegram_bot.stats import APPROVAL_WATCHER_TIME, NEW_PENDING_APPROVAL_COUNTER

LOGGER = logging.getLogger(__name__)


class Monitor(RegularIntervalWorker):

    def __init__(self, config: Config, api_client: KeelApiClient, bot: KeelTelegramBot, store: Store):
        interval_seconds = config.MONITOR_INTERVAL.value.total_seconds()
        super().__init__(interval_seconds)
        self._config = config
        self._api_client = api_client
        self._bot = bot
        self._store = store

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

        chat_ids = [int(x) for x in self._config.TELEGRAM_CHAT_IDS.value]
        approval_ids = [x.id for x in active]
        if self._store.seed_announced(approval_ids, chat_ids):
            # first start with a new database: these were announced by a version without persistence
            LOGGER.info(f"New database, not announcing the {len(approval_ids)} approvals that are pending already")
            return

        self._store.forget_announced_except(approval_ids)

        for item in active:
            if await self._bot.on_new_pending_approval(item):
                NEW_PENDING_APPROVAL_COUNTER.inc()

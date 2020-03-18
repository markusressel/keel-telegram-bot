from keel_telegram_bot.api_client import KeelApiClient
from keel_telegram_bot.bot import KeelTelegramBot
from keel_telegram_bot.config import Config
from keel_telegram_bot.monitoring import RegularIntervalWorker
from keel_telegram_bot.stats import APPROVAL_WATCHER_TIME
from keel_telegram_bot.util import filter_new_by_key


class Monitor(RegularIntervalWorker):

    def __init__(self, config: Config, api_client: KeelApiClient, bot: KeelTelegramBot):
        interval_seconds = config.MONITOR_INTERVAL.value.total_seconds()
        super().__init__(interval_seconds)
        self._config = config
        self._api_client = api_client
        self._bot = bot
        self._old = None

    @APPROVAL_WATCHER_TIME.time()
    def _run(self):
        new = self._api_client.get_approvals(rejected=False, archived=False)
        if self._old is None:
            self._old = new
            return

        new_pending = filter_new_by_key(self._old, new, key=lambda x: x["id"])
        self._old = new

        for item in new_pending:
            self._bot.on_new_pending_approval(item)

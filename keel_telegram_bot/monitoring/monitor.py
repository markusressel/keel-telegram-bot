from keel_telegram_bot.api_client import KeelApiClient
from keel_telegram_bot.bot import KeelTelegramBot
from keel_telegram_bot.config import Config
from keel_telegram_bot.monitoring import RegularIntervalWorker
from keel_telegram_bot.util import filter_new_by_key, approval_to_str


class Monitor(RegularIntervalWorker):

    def __init__(self, config: Config, api_client: KeelApiClient, bot: KeelTelegramBot):
        interval_seconds = config.MONITOR_INTERVAL.value.total_seconds()
        super().__init__(interval_seconds)
        self._config = config
        self._api_client = api_client
        self._bot = bot
        self._old = None

    def _run(self):
        new = self._api_client.get_approvals(rejected=False)
        if self._old is None:
            self._old = new
            return

        new_pending = filter_new_by_key(self._old, new, key=lambda x: x["id"])
        self._old = new

        if len(new_pending) <= 0:
            return

        text = "\n".join([
            f"**New pending approvals ({len(new_pending)}):**",
            *list(map(approval_to_str, new_pending))
        ])
        self._bot.notify(text)

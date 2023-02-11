import asyncio
import logging
import os
import sys

from container_app_conf.formatter.toml import TomlFormatter
from prometheus_client import start_http_server

from keel_telegram_bot.api_client import KeelApiClient
from keel_telegram_bot.bot import KeelTelegramBot
from keel_telegram_bot.config import Config
from keel_telegram_bot.monitoring.monitor import Monitor
from keel_telegram_bot.webserver import WebsocketServer

parent_dir = os.path.abspath(os.path.join(os.path.abspath(__file__), "..", ".."))
sys.path.append(parent_dir)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
LOGGER = logging.getLogger(__name__)


def main():
    config = Config()

    log_level = logging._nameToLevel.get(str(config.LOG_LEVEL.value).upper(), config.LOG_LEVEL.default)
    logging.getLogger("keel_telegram_bot").setLevel(log_level)

    LOGGER.debug("Config:\n{}".format(config.print(TomlFormatter())))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # start prometheus server
    if config.STATS_ENABLED.value:
        start_http_server(config.STATS_PORT.value)

    api_client = KeelApiClient(
        config.KEEL_HOST.value,
        config.KEEL_PORT.value,
        config.KEEL_SSL.value,
        config.KEEL_USER.value,
        config.KEEL_PASSWORD.value,
    )

    bot = KeelTelegramBot(config, api_client)
    monitor = Monitor(config, api_client, bot)
    server = WebsocketServer(config, bot)

    tasks = asyncio.gather(
        bot.start(),
        monitor.start(),
        server.start(),
    )

    loop.run_until_complete(tasks)
    loop.run_forever()

    # monitor.stop()
    # bot.stop()


if __name__ == '__main__':
    main()

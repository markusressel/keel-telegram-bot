import unittest

from keel_telegram_bot.config import Config


class TestBase(unittest.TestCase):
    from container_app_conf.source.yaml_source import YamlSource

    # load config from test folder
    config = Config(
        singleton=True,
        data_sources=[
            YamlSource("keel-telegram-bot.yaml", "./tests/")
        ]
    )

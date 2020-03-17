import logging
import re

from container_app_conf import ConfigBase
from container_app_conf.entry.bool import BoolConfigEntry
from container_app_conf.entry.int import IntConfigEntry
from container_app_conf.entry.list import ListConfigEntry
from container_app_conf.entry.string import StringConfigEntry
from container_app_conf.entry.timedelta import TimeDeltaConfigEntry
from container_app_conf.source.env_source import EnvSource
from container_app_conf.source.toml_source import TomlSource
from container_app_conf.source.yaml_source import YamlSource

NODE_MAIN = "keel-telegram-bot"

NODE_TELEGRAM = "telegram"

NODE_KEEL = "keel"
NODE_HOST = "host"
NODE_WEBHOOK = "webhook"

NODE_STATS = "stats"
NODE_ENABLED = "enabled"
NODE_PORT = "port"


class Config(ConfigBase):

    def __new__(cls, *args, **kwargs):
        yaml_source = YamlSource(NODE_MAIN)
        toml_source = TomlSource(NODE_MAIN)
        data_sources = [
            EnvSource(),
            yaml_source,
            toml_source
        ]
        return super(Config, cls).__new__(cls, data_sources=data_sources)

    LOG_LEVEL = StringConfigEntry(
        description="Log level",
        key_path=[
            NODE_MAIN,
            "log_level"
        ],
        regex=re.compile(f"{'|'.join(logging._nameToLevel.keys())}", flags=re.IGNORECASE),
        default="WARNING",
    )

    TELEGRAM_BOT_TOKEN = StringConfigEntry(
        description="The telegram bot token to use",
        key_path=[
            NODE_MAIN,
            NODE_TELEGRAM,
            "bot_token"
        ],
        example="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        secret=True,
        required=True
    )

    TELEGRAM_ADMIN_USERNAMES = ListConfigEntry(
        item_type=StringConfigEntry,
        key_path=[
            NODE_MAIN,
            NODE_TELEGRAM,
            "admin_usernames"
        ],
        required=True,
        example=[
            "myadminuser",
            "myotheradminuser"
        ]
    )

    TELEGRAM_CHAT_IDS = ListConfigEntry(
        item_type=StringConfigEntry,
        key_path=[
            NODE_MAIN,
            NODE_TELEGRAM,
            "chat_ids"
        ],
        required=True,
        example=[
            12345678,
            87654321
        ]
    )

    KEEL_HOST = StringConfigEntry(
        description="Hostname of the keel HTTP endpoint",
        key_path=[
            NODE_MAIN,
            NODE_KEEL,
            NODE_HOST
        ],
        default="localhost",
        required=True
    )

    KEEL_PORT = IntConfigEntry(
        description="Port of the keel HTTP endpoint",
        key_path=[
            NODE_MAIN,
            NODE_KEEL,
            NODE_PORT
        ],
        default=9300,
        required=True
    )

    KEEL_SSL = BoolConfigEntry(
        description="Whether to use HTTPS or not",
        key_path=[
            NODE_MAIN,
            NODE_KEEL,
            "ssl"
        ],
        default=True
    )

    KEEL_USER = StringConfigEntry(
        description="Keel basic auth username",
        key_path=[
            NODE_MAIN,
            NODE_KEEL,
            "username"
        ],
        required=True
    )

    KEEL_PASSWORD = StringConfigEntry(
        description="Keel basic auth password",
        key_path=[
            NODE_MAIN,
            NODE_KEEL,
            "password"
        ],
        required=True,
        secret=True
    )

    MONITOR_INTERVAL = TimeDeltaConfigEntry(
        description="Interval to check for new pending approvals",
        key_path=[
            NODE_MAIN,
            "monitor"
            "interval"
        ],
        default="1m",
        required=True,
    )

    STATS_ENABLED = BoolConfigEntry(
        description="Whether to enable prometheus statistics or not.",
        key_path=[
            NODE_MAIN,
            NODE_STATS,
            NODE_ENABLED
        ],
        default=True
    )

    STATS_PORT = IntConfigEntry(
        description="The port to expose statistics on.",
        key_path=[
            NODE_MAIN,
            NODE_STATS,
            NODE_PORT
        ],
        default=8000
    )

from telegram import Update
from telegram.ext import CallbackContext
from telegram_click.permission.base import Permission

from keel_telegram_bot.config import Config


class _ConfigAdmins(Permission):

    def __init__(self):
        self._config = Config()

    def evaluate(self, update: Update, context: CallbackContext) -> bool:
        from_user = update.effective_message.from_user
        return from_user.username in self._config.TELEGRAM_ADMIN_USERNAMES.value


CONFIG_ADMINS = _ConfigAdmins()


class _ConfigChatId(Permission):

    def __init__(self):
        self._config = Config()

    def evaluate(self, update: Update, context: CallbackContext) -> bool:
        chat_id = update.effective_message.chat_id
        return chat_id in self._config.TELEGRAM_CHAT_IDS.value


CONFIGURED_CHAT_ID = _ConfigChatId()

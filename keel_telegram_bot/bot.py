import logging

from telegram import Update, ParseMode
from telegram.ext import CommandHandler, Filters, MessageHandler, Updater, CallbackContext
from telegram_click.argument import Argument
from telegram_click.decorator import command

from keel_telegram_bot.api_client import KeelApiClient
from keel_telegram_bot.config import Config
from keel_telegram_bot.const import *
from keel_telegram_bot.permissions import CONFIG_ADMINS
from keel_telegram_bot.stats import COMMAND_TIME_START, COMMAND_TIME_LIST_APPROVALS, COMMAND_TIME_APPROVE, \
    COMMAND_TIME_REJECT
from keel_telegram_bot.util import send_message

LOGGER = logging.getLogger(__name__)


class KeelTelegramBot:
    """
    The main entry class of the keel telegram bot
    """

    def __init__(self, config: Config, api_client: KeelApiClient):
        """
        Creates an instance.
        :param config: configuration object
        """
        self._config = config
        self._api_client = api_client

        self._updater = Updater(token=self._config.TELEGRAM_BOT_TOKEN.value, use_context=True)
        LOGGER.debug("Using bot id '{}' ({})".format(self._updater.bot.id, self._updater.bot.name))

        self._dispatcher = self._updater.dispatcher

        handler_groups = {
            0: [],
            1: [
                CommandHandler(COMMAND_START,
                               filters=(~ Filters.reply) & (~ Filters.forwarded),
                               callback=self._start_callback),
                CommandHandler(COMMAND_LIST_APPROVALS,
                               filters=(~ Filters.reply) & (~ Filters.forwarded),
                               callback=self._list_approvals_callback),
                CommandHandler(COMMAND_APPROVE,
                               filters=(~ Filters.reply) & (~ Filters.forwarded),
                               callback=self._approve_callback),
                CommandHandler(COMMAND_REJECT,
                               filters=(~ Filters.reply) & (~ Filters.forwarded),
                               callback=self._reject_callback),

                CommandHandler(COMMAND_HELP,
                               filters=(~ Filters.reply) & (~ Filters.forwarded),
                               callback=self._help_callback),
                # unknown command handler
                MessageHandler(
                    filters=Filters.command & (~ Filters.forwarded),
                    callback=self._unknown_command_callback),
            ]
        }

        for group, handlers in handler_groups.items():
            for handler in handlers:
                self._updater.dispatcher.add_handler(handler, group=group)

    @property
    def bot(self):
        return self._updater.bot

    def start(self):
        """
        Starts up the bot.
        """
        self._updater.start_polling()
        self._updater.idle()

    def stop(self):
        """
        Shuts down the bot.
        """
        self._updater.stop()

    @COMMAND_TIME_START.time()
    def _start_callback(self, update: Update, context: CallbackContext) -> None:
        """
        Welcomes a new user with a greeting message
        :param update: the chat update object
        :param context: telegram context
        """
        bot = context.bot
        chat_id = update.effective_chat.id
        user_first_name = update.effective_user.first_name

        if not CONFIG_ADMINS.evaluate(update, context):
            send_message(bot, chat_id, "Sorry, you do not have permissions to use this bot.")
            return

        send_message(bot, chat_id,
                     f"Welcome {user_first_name},\nthis is your keel-telegram-bot instance, ready to go!")

    @COMMAND_TIME_LIST_APPROVALS.time()
    @command(name=COMMAND_TIME_LIST_APPROVALS,
             description="List pending approvals",
             arguments=[
                 Argument(name=["rejected", "r"], description="Rejected", type=bool, example="true", optional=True),
                 Argument(name=["archived", "a"], description="Archived", type=bool, example="true", optional=True),
             ],
             permissions=CONFIG_ADMINS)
    def _list_approvals_callback(self, update: Update, context: CallbackContext,
                                 rejected: bool or None, archived: bool or None) -> None:
        """
        List pending approvals
        """
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id

        items = self._api_client.get_approvals(rejected, archived)
        if len(items) <= 0:
            text = "No pending approvals"
        else:
            items = list(map(lambda x: x["identifier"], items))
            text = "\n".join(items)
        send_message(bot, chat_id, text, reply_to=message.message_id)

    @COMMAND_TIME_APPROVE.time()
    @command(name=COMMAND_TIME_APPROVE,
             description="Approve a pending item",
             arguments=[
                 Argument(name=["identifier", "id"], description="Approval identifier",
                          example="default/myimage:1.5.5"),
                 Argument(name=["voter", "v"], description="Name of voter", example="john", optional=True),
             ],
             permissions=CONFIG_ADMINS)
    def _approve_callback(self, update: Update, context: CallbackContext,
                          identifier: str, voter: str or None) -> None:
        """
        Approve a pending item
        """
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id

        if voter is None:
            voter = update.effective_user.full_name

        self._api_client.approve(identifier, voter)
        text = "Success"
        send_message(bot, chat_id, text, reply_to=message.message_id)

    @COMMAND_TIME_REJECT.time()
    @command(name=COMMAND_TIME_REJECT,
             description="Reject a pending item",
             arguments=[
                 Argument(name=["identifier", "id"], description="Approval identifier",
                          example="default/myimage:1.5.5"),
                 Argument(name=["voter", "v"], description="Name of voter", example="john", optional=True),
             ],
             permissions=CONFIG_ADMINS)
    def _reject_callback(self, update: Update, context: CallbackContext,
                         identifier: str, voter: str or None) -> None:
        """
        Reject a pending item
        """
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id

        if voter is None:
            voter = update.effective_user.full_name

        self._api_client.reject(identifier, voter)
        text = "Success"
        send_message(bot, chat_id, text, reply_to=message.message_id)

    @command(
        name=COMMAND_HELP,
        description="List commands supported by this bot.",
        permissions=CONFIG_ADMINS,
    )
    def _help_callback(self, update: Update, context: CallbackContext):
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id

        from telegram_click import generate_command_list
        text = generate_command_list(update, context)
        send_message(bot, chat_id, text,
                     parse_mode=ParseMode.MARKDOWN,
                     reply_to=message.message_id)

    def _unknown_command_callback(self, update: Update, context: CallbackContext) -> None:
        """
        Handles unknown commands send by a user
        :param update: the chat update object
        :param context: telegram context
        """
        message = update.effective_message
        username = "N/A"
        if update.effective_user is not None:
            username = update.effective_user.username

        user_is_admin = username in self._config.TELEGRAM_ADMIN_USERNAMES.value
        if user_is_admin:
            self._help_callback(update, context)
            return

import logging
import re
from typing import Dict

from requests import HTTPError
from telegram import Update, ParseMode, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import CommandHandler, Filters, MessageHandler, Updater, CallbackContext, CallbackQueryHandler
from telegram_click.argument import Argument
from telegram_click.decorator import command

from keel_telegram_bot.api_client import KeelApiClient
from keel_telegram_bot.bot.permissions import CONFIG_ADMINS
from keel_telegram_bot.bot.reply_keyboard_handler import ReplyKeyboardHandler
from keel_telegram_bot.config import Config
from keel_telegram_bot.const import *
from keel_telegram_bot.stats import COMMAND_TIME_START, COMMAND_TIME_LIST_APPROVALS, COMMAND_TIME_APPROVE, \
    COMMAND_TIME_REJECT, COMMAND_TIME_DELETE
from keel_telegram_bot.util import send_message, approval_to_str

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

        self._response_handler = ReplyKeyboardHandler()

        self._updater = Updater(token=self._config.TELEGRAM_BOT_TOKEN.value, use_context=True)
        LOGGER.debug(f"Using bot id '{self._updater.bot.id}' ({self._updater.bot.name})")
        self._dispatcher = self._updater.dispatcher

        handler_groups = {
            0: [CallbackQueryHandler(callback=self._inline_keyboard_click_callback)],
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
                CommandHandler(COMMAND_DELETE,
                               filters=(~ Filters.reply) & (~ Filters.forwarded),
                               callback=self._delete_callback),

                CommandHandler(COMMAND_HELP,
                               filters=(~ Filters.reply) & (~ Filters.forwarded),
                               callback=self._help_callback),
                CommandHandler(CANCEL_KEYBOARD_COMMAND[1:],
                               filters=(~ Filters.reply) & (~ Filters.forwarded),
                               callback=self._response_handler.cancel_keyboard_callback),
                # unknown command handler
                MessageHandler(
                    filters=Filters.command & (~ Filters.forwarded),
                    callback=self._unknown_command_callback),
                MessageHandler(
                    filters=(~ Filters.forwarded),
                    callback=self._any_message_callback),
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
    @command(name=COMMAND_LIST_APPROVALS,
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

        rejected_items = list(filter(lambda x: x[KEY_REJECTED], items))
        archived_items = list(filter(lambda x: x[KEY_ARCHIVED], items))
        pending_items = list(filter(
            lambda x: x not in archived_items and x not in rejected_items
                      and x[KEY_VOTES_RECEIVED] < x[KEY_VOTES_REQUIRED], items))
        approved_items = list(
            filter(lambda x: x not in rejected_items and x not in archived_items and x not in pending_items, items))

        text = "\n".join([
            f"<b>Pending ({len(pending_items)}):</b>",
            "\n\n".join(list(map(lambda x: "> " + approval_to_str(x), pending_items))),
            f"<b>Approved ({len(approved_items)}):</b>",
            "\n\n".join(list(map(lambda x: "> " + approval_to_str(x), approved_items))),
            f"<b>Rejected ({len(rejected_items)}):</b>",
            "\n\n".join(list(map(lambda x: "> " + approval_to_str(x), rejected_items))),
            f"<b>Archived ({len(archived_items)}):</b>",
            "\n\n".join(list(map(lambda x: "> " + approval_to_str(x), archived_items)))
        ])

        send_message(bot, chat_id, text, reply_to=message.message_id, parse_mode=ParseMode.HTML)

    @COMMAND_TIME_APPROVE.time()
    @command(name=COMMAND_APPROVE,
             description="Approve a pending item",
             arguments=[
                 Argument(name=["identifier", "i"], description="Approval identifier",
                          example="default/myimage:1.5.5"),
                 Argument(name=["voter", "v"], description="Name of voter", example="john", optional=True),
             ],
             permissions=CONFIG_ADMINS)
    def _approve_callback(self, update: Update, context: CallbackContext,
                          identifier: str, voter: str or None) -> None:
        """
        Approve a pending item
        """
        if voter is None:
            voter = update.effective_user.full_name

        def execute(update: Update, context: CallbackContext, item: dict, data: dict):
            bot = context.bot
            message = update.effective_message
            chat_id = update.effective_chat.id

            self._api_client.approve(item["id"], item["identifier"], voter)
            text = f"Approved {item['identifier']}"
            send_message(bot, chat_id, text, reply_to=message.message_id, menu=ReplyKeyboardRemove(selective=True))

        items = self._api_client.get_approvals(rejected=False, archived=False)
        self._response_handler.await_user_selection(
            update, context, identifier, choices=items, key=lambda x: x["identifier"],
            callback=execute,
        )

    @COMMAND_TIME_REJECT.time()
    @command(name=COMMAND_REJECT,
             description="Reject a pending item",
             arguments=[
                 Argument(name=["identifier", "i"], description="Approval identifier", example="default/myimage:1.5.5"),
                 Argument(name=["voter", "v"], description="Name of voter", example="john", optional=True),
             ],
             permissions=CONFIG_ADMINS)
    def _reject_callback(self, update: Update, context: CallbackContext,
                         identifier: str, voter: str or None) -> None:
        """
        Reject a pending item
        """
        if voter is None:
            voter = update.effective_user.full_name

        def execute(update: Update, context: CallbackContext, item: dict, data: dict):
            bot = context.bot
            message = update.effective_message
            chat_id = update.effective_chat.id

            self._api_client.reject(item["id"], item["identifier"], voter)
            text = f"Rejected {item['identifier']}"
            send_message(bot, chat_id, text, reply_to=message.message_id, menu=ReplyKeyboardRemove(selective=True))

        items = self._api_client.get_approvals(rejected=False, archived=False)
        self._response_handler.await_user_selection(
            update, context, identifier, choices=items, key=lambda x: x["identifier"],
            callback=execute,
        )

    @COMMAND_TIME_DELETE.time()
    @command(name=COMMAND_DELETE,
             description="Delete an approval item",
             arguments=[
                 Argument(name=["identifier", "i"], description="Approval identifier", example="default/myimage:1.5.5"),
                 Argument(name=["voter", "v"], description="Name of voter", example="john", optional=True),
             ],
             permissions=CONFIG_ADMINS)
    def _delete_callback(self, update: Update, context: CallbackContext,
                         identifier: str, voter: str or None) -> None:
        """
        Delete an archived item
        """
        if voter is None:
            voter = update.effective_user.full_name

        def execute(update: Update, context: CallbackContext, item: dict, data: dict):
            bot = context.bot
            message = update.effective_message
            chat_id = update.effective_chat.id

            self._api_client.delete(item["id"], item["identifier"], voter)
            text = f"Deleted {item['identifier']}"
            send_message(bot, chat_id, text, reply_to=message.message_id, menu=ReplyKeyboardRemove(selective=True))

        items = self._api_client.get_approvals()
        self._response_handler.await_user_selection(
            update, context, identifier, choices=items, key=lambda x: x["identifier"],
            callback=execute,
        )

    def on_notification(self, data: dict):
        """
        Handles incoming notifications (via Webhook)
        :param data: notification data
        """
        identifier = data.get("identifier", None)
        title = data.get("name", None)
        type = data.get("type", None)
        level = data.get("level", None)  # success/failure
        message = data.get("message", None)

        text = "\n".join([
            f"<b>{title}: {level}</b>",
            f"{identifier}",
            f"{type}",
            f"{message}",
        ])

        for chat_id in self._config.TELEGRAM_CHAT_IDS.value:
            send_message(
                self.bot, chat_id,
                text, parse_mode=ParseMode.HTML,
                menu=None
            )

    def on_new_pending_approval(self, item: dict):
        """
        Handles new pending approvals by sending a message
        including an inline keyboard to all configured chat ids
        :param item: new pending approval
        """
        text = approval_to_str(item)

        keyboard_items = {
            "Approve": BUTTON_DATA_APPROVE,
            "Reject": BUTTON_DATA_REJECT
        }
        keyboard = self._build_inline_keyboard(keyboard_items)

        for chat_id in self._config.TELEGRAM_CHAT_IDS.value:
            send_message(
                self.bot, chat_id,
                text, parse_mode=ParseMode.HTML,
                menu=keyboard
            )

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

    def _any_message_callback(self, update: Update, context: CallbackContext) -> None:
        """
        Used to respond to response keyboard entry selections
        :param update: the chat update object
        :param context: telegram context
        """
        self._response_handler.on_message(update, context)

    def _inline_keyboard_click_callback(self, update: Update, context: CallbackContext):
        """
        Handles inline keyboard button click callbacks
        :param update:
        :param context:
        """
        bot = context.bot
        from_user = update.callback_query.from_user

        message_text = update.effective_message.text
        query = update.callback_query
        query_id = query.id
        data = query.data

        try:
            matches = re.search(r"^Id: (.*)", message_text, flags=re.MULTILINE)
            approval_id = matches.group(1)
            matches = re.search(r"^Identifier: (.*)", message_text, flags=re.MULTILINE)
            approval_identifier = matches.group(1)

            if data == BUTTON_DATA_APPROVE:
                self._api_client.approve(approval_id, approval_identifier, from_user.full_name)
                answer_text = f"Approved '{approval_identifier}'"
                keyboard = self._build_inline_keyboard({"Approved": ""})
            elif data == BUTTON_DATA_REJECT:
                self._api_client.reject(approval_id, approval_identifier, from_user.full_name)
                answer_text = f"Rejected '{approval_identifier}'"
                keyboard = self._build_inline_keyboard({"Rejected": ""})
            else:
                bot.answer_callback_query(query_id, text="Unknown button")
                return

            # remove buttons
            query.edit_message_reply_markup(reply_markup=keyboard)
            context.bot.answer_callback_query(query_id, text=answer_text)
        except HTTPError as e:
            LOGGER.error(e)
            bot.answer_callback_query(query_id, text=f"{e.response.content.decode('utf-8')}")
        except Exception as e:
            LOGGER.error(e)
            bot.answer_callback_query(query_id, text=f"Unknwon error")

    @staticmethod
    def _build_inline_keyboard(items: Dict[str, str]) -> InlineKeyboardMarkup:
        """
        Builds an inline button menu
        :param items: dictionary of "button text" -> "callback data" items
        :return: reply markup
        """
        keyboard = list(map(lambda x: InlineKeyboardButton(x[0], callback_data=x[1]), items.items()))
        return InlineKeyboardMarkup.from_column(keyboard)

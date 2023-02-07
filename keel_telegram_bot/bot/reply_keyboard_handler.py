import logging
from typing import List, Any

from telegram import Update, ReplyKeyboardRemove, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext

from keel_telegram_bot.const import CANCEL_KEYBOARD_COMMAND
from keel_telegram_bot.util import send_message, fuzzy_match

LOGGER = logging.getLogger(__name__)


class ReplyKeyboardHandler:
    # this map is used to remember from which users we
    # are currently awaiting a response message
    awaiting_response = {}

    def __init__(self):
        pass

    async def on_message(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        text = update.effective_message.text

        if user_id not in self.awaiting_response:
            return

        data = self.awaiting_response[user_id]
        if text not in data["valid_responses"]:
            return

        LOGGER.debug("Awaited response from user {} received: {}".format(user_id, text))
        try:
            await data["callback"](update, context, text, data["callback_data"])
            self.awaiting_response.pop(user_id)
        except Exception as e:
            LOGGER.exception(e)

    async def _on_user_selection(self, update: Update, context: CallbackContext, message: str, data: dict):
        """
        Called when a user selection is awaited and user message arrives
        :param update:
        :param context:
        :param message:
        :param data:
        """
        await self.await_user_selection(update, context, message, data["choices"], data["key"],
                                        data["callback"], data["callback_data"])

    async def await_user_selection(self, update: Update, context: CallbackContext,
                                   selection: str or None, choices: List[Any], key: callable,
                                   callback: callable, callback_data: dict = None):
        """
        Sends a ReplyKeyboard to the user and waits for a valid selection.
        :param update: Update
        :param context: CallbackContext
        :param selection: the current user selection (if any)
        :param choices: list of choices to select from
        :param key: function to create unique string key for a choice
        :param callback: the function to call, when a selection was made
        :param callback_data: data to pass to the callback function
        """
        bot = context.bot
        chat_id = update.effective_chat.id
        message_id = update.effective_message.message_id
        user_id = update.effective_user.id

        fuzzy_matches = fuzzy_match(selection, choices=choices, key=key, limit=5)

        # check if something matches perfectly
        perfect_matches = list(filter(lambda x: x[1] == 100, fuzzy_matches))
        if len(perfect_matches) == 1:
            choice = perfect_matches[0][0]
            await callback(update, context, choice, callback_data)
            return

        # send reply keyboard with fuzzy matches to user
        keyboard_texts = list(map(lambda x: "{}".format(key(x[0])), fuzzy_matches))
        keyboard = self.build_reply_keyboard(keyboard_texts)
        text = "No unique perfect match found, please select one of the menu options"
        self.await_response(
            user_id=user_id,
            options=keyboard_texts,
            callback=self._on_user_selection,
            callback_data={
                "choices": choices,
                "key": key,
                "callback": callback,
                "callback_data": callback_data,
            })
        await send_message(bot, chat_id, text, parse_mode="MARKDOWN", reply_to=message_id, menu=keyboard)

    def await_response(self, user_id: str, options: List[str], callback_data: dict, callback):
        """
        Remember, that we are awaiting a response message from a user
        :param user_id: the user id
        :param options: a list of messages that the user can send as a valid response
        :param callback: function to call with callback data
        :param callback_data: data to pass to callback
        """
        if user_id in self.awaiting_response:
            raise AssertionError("Already awaiting response to a previous query from user {}".format(user_id))

        self.awaiting_response[user_id] = {
            "valid_responses": options,
            "callback": callback,
            "callback_data": callback_data
        }

    def cancel_keyboard_callback(self, update: Update, context: CallbackContext):
        bot = context.bot
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        message_id = update.effective_message.message_id

        text = "Cancelled"
        await send_message(bot, chat_id, text, reply_to=message_id, menu=ReplyKeyboardRemove(selective=True))

        if user_id in self.awaiting_response:
            self.awaiting_response.pop(user_id)

    @staticmethod
    def build_reply_keyboard(items: List[str]) -> ReplyKeyboardMarkup:
        """
        Builds a menu to select an item from a list
        :param items: list of items to choose from
        :return: reply markup
        """
        items.append(CANCEL_KEYBOARD_COMMAND)
        keyboard = list(map(lambda x: KeyboardButton(x), items))
        # NOTE: the "selective=True" requires the menu to be sent as a reply
        # (or with an @username mention)
        return ReplyKeyboardMarkup.from_column(keyboard, one_time_keyboard=True, selective=True)

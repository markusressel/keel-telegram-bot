import functools
import logging
import operator
from typing import List, Any

from telegram import Bot, Message, ReplyMarkup

from keel_telegram_bot.config import Config

LOGGER = logging.getLogger(__name__)

CONFIG = Config()


def flatten(data: List[List[Any]]) -> List[Any]:
    """
    Flattens a list of lists
    :param data: the data to flatten
    :return: flattened list
    """
    return functools.reduce(operator.iconcat, data, [])


def format_for_single_line_log(text: str) -> str:
    """
    Formats a text for log
    :param text:
    :return:
    """
    text = "" if text is None else text
    return " ".join(text.split())


def send_message(bot: Bot, chat_id: str, message: str, parse_mode: str = None, reply_to: int = None,
                 menu: ReplyMarkup = None) -> Message:
    """
    Sends a text message to the given chat
    :param bot: the bot
    :param chat_id: the chat product_id to send the message to
    :param message: the message to chat (may contain emoji aliases)
    :param parse_mode: specify whether to parse the text as markdown or HTML
    :param reply_to: the message product_id to reply to
    :param menu: inline keyboard menu markup
    """
    from emoji import emojize

    emojized_text = emojize(message, use_aliases=True)
    return bot.send_message(chat_id=chat_id, parse_mode=parse_mode, text=emojized_text, reply_to_message_id=reply_to,
                            reply_markup=menu)

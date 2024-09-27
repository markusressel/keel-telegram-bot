import functools
import logging
import operator
import re
from datetime import datetime, timezone, timedelta
from typing import List, Any, Tuple, Dict

from telegram import Bot, Message
from telegram._utils.types import ReplyMarkup

from keel_telegram_bot.client.approval import Approval
from keel_telegram_bot.client.resource import Resource
from keel_telegram_bot.config import Config

LOGGER = logging.getLogger(__name__)

CONFIG = Config()


def _is_filtered_for(filters: List[Dict], chat_id: str, identifier: str) -> bool:
    for config in filters:
        filter_chat_id = config["chat_id"]
        identifier_regex = config["identifier"]

        if str(filter_chat_id) == str(chat_id):
            identifier_pattern = re.compile(identifier_regex)
            result = identifier_pattern.search(identifier)
            if result is None:
                return True

    return False


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


async def send_message(bot: Bot, chat_id: str, message: str, parse_mode: str = None, reply_to: int = None,
                       menu: ReplyMarkup = None) -> Message or List[Message]:
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

    emojized_text = emojize(message, language='alias')

    # automatically split long messages
    messages = []
    for i in range(0, len(emojized_text), 4096):
        message_part = emojized_text[i:i + 4096]

        message = await bot.send_message(
            chat_id=chat_id, parse_mode=parse_mode, text=message_part,
            reply_to_message_id=reply_to,
            reply_markup=menu
        )
        messages.append(message)

    if len(messages) == 1:
        return messages[0]
    return messages


def fuzzy_match(term: str, choices: List[Any], limit: int = None, key=lambda x: x, ignorecase: bool = True) -> List[
    Tuple[Any, int]]:
    """
    Does a fuzzy search on the given choices
    :param term: the search term
    :param choices: list of possible choices
    :param key: function to turn a choice item into a string
    :param limit: Optional maximum for the number of elements returned
    :return: List of (choice, ratio) tuples, sorted by descending ratio
    """
    # map choices to key
    if ignorecase:
        term = term.casefold()
    choices = filter(lambda x: key(x) is not None, choices)
    key_map = dict(map(lambda x: (key(x).casefold() if ignorecase else key(x), x), choices))

    from fuzzywuzzy import process
    from fuzzywuzzy import fuzz
    matches = process.extract(term, key_map.keys(), limit=limit, scorer=fuzz.UWRatio)

    # map results back to original choices
    result = list(map(lambda x: (key_map[x[0]], x[1]), matches))

    return result


def filter_new_by_key(a: List, b: List, key: callable) -> List:
    """
    Returns a list of all items, that are new in b when compared to a,
    using the key function to determine a unique identifier for list items
    :param a: "old" list
    :param b: "new" list
    :param key: function to map list items to a unique identifier
    :return: new list items
    """
    a_ids = set(map(key, a))
    b_ids = set(map(key, b))
    new_ids = b_ids - a_ids

    result = []
    for id in new_ids:
        item_in_b = list(filter(lambda x: key(x) == id, b))[0]
        result.append(item_in_b)
    return result


def approval_to_str(data: Approval) -> str:
    id = data.id
    identifier = data.identifier
    current_version = data.currentVersion
    new_version = data.newVersion
    votes_required = data.votesRequired
    votes_received = data.votesReceived
    deadline = data.deadline
    message = data.message

    now_utc = datetime.now().replace(microsecond=0).astimezone(tz=timezone.utc)
    deadline_diff = timedelta(seconds=(deadline.replace(microsecond=0) - now_utc).total_seconds())

    deadline_abs_str = deadline.strftime('%m/%d %H:%M:%S')
    deadline_remaining_str = deadline_diff_to_str(deadline_diff)

    text = "\n".join([
        f"<b>{message}</b>",
        f"Id: {id}",
        f"Identifier: {identifier}",
        f"Version: {current_version} -> {new_version}",
        f"Votes: {votes_received}/{votes_required}",
        f"Expires: {deadline_abs_str} ({deadline_remaining_str})"
    ])

    return text


def resource_to_str(r: Resource) -> str:
    image_lines = list(map(lambda x: f"    {x}", r.images))
    return "\n".join(
        [f"> {r.namespace}/{r.name} P: {r.policy.value}"] + image_lines
    )


def deadline_diff_to_str(deadline_diff) -> str:
    units = []

    days = deadline_diff.days if deadline_diff.days else ""
    if days:
        units.append(f"{days}d")

    hours = deadline_diff.seconds // 3600
    if hours:
        units.append(f"{hours}h")

    minutes = (deadline_diff.seconds // 60) % 60
    if minutes:
        units.append(f"{minutes}m")

    seconds = int(deadline_diff.seconds) % 60
    if seconds:
        units.append(f"{seconds}s")

    return "".join(units)

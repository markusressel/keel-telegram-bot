import functools
import html
import logging
import operator
import re
from datetime import datetime, timezone, timedelta
from typing import List, Any, Tuple, Dict, Callable, Optional

from telegram import Bot, Message, LinkPreviewOptions
from telegram._utils.types import ReplyMarkup

from keel_telegram_bot.client.approval import Approval
from keel_telegram_bot.client.resource import Resource
from keel_telegram_bot.client.tracked_image import TrackedImage
from keel_telegram_bot.config import Config
from keel_telegram_bot.helm.chart import HelmChart
from keel_telegram_bot.helm.checker import HelmChartCheckResult
from keel_telegram_bot.helm.index import HelmChartUpdate, ChartVersion

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


async def send_message(
    bot: Bot, chat_id: str, message: str, parse_mode: str = None, reply_to: int = None,
    menu: ReplyMarkup = None,
    link_preview_options: LinkPreviewOptions = LinkPreviewOptions(is_disabled=True)
) -> Message | List[Message]:
    """
    Sends a text message to the given chat
    :param bot: the bot
    :param chat_id: the chat product_id to send the message to
    :param message: the message to chat (may contain emoji aliases)
    :param parse_mode: specify whether to parse the text as markdown or HTML
    :param reply_to: the message product_id to reply to
    :param menu: inline keyboard menu markup
    :param link_preview_options: link preview options
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
            reply_markup=menu,
            link_preview_options=link_preview_options
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
    :param limit: Optional maximum for the number of elements returned
    :param key: function to turn a choice item into a string
    :param ignorecase: whether to ignore case when matching
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


def filter_new_by_key(a: List, b: List, key: Callable) -> List:
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
    header_line = f"> {r.identifier}"
    policy_lines = ["  Policy: " + r.policy.value]

    image_lines = []
    if len(r.images) > 1:
        image_lines = list(map(lambda x: f"    {x}", r.images))
        image_lines = ["  Images:"] + image_lines
    elif len(r.images) == 1:
        image_lines = ["  Image: " + r.images[0]]

    label_lines = []
    if len(r.labels) > 0:
        label_lines = list(map(lambda x: f"    {x}: {r.labels[x]}", r.labels))
        label_lines = ["  Labels:"] + label_lines

    annotation_lines = []
    if len(r.annotations) > 0:
        filtered_annotations = {}
        for key, value in r.annotations.items():
            if key.startswith("keel.sh"):
                filtered_annotations[key] = value

        annotation_lines = list(
            map(lambda x: f"    {x[0]}: {x[1]}", filtered_annotations.items()))
        annotation_lines = ["  Annotations:"] + annotation_lines

    return "\n".join(
        [header_line]
        + policy_lines
        + image_lines
        + annotation_lines
        + label_lines
    )


def tracked_image_to_str(data: TrackedImage) -> str:
    return f"{data.provider}/{data.namespace}/{data.image} ({data.policy.value})"


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


HELM_CHART_CHANGES_LIMIT = 10
HELM_CHART_CHANGE_LENGTH_LIMIT = 200


def helm_chart_update_to_str(chart: HelmChart, update: HelmChartUpdate, manual_reason: Optional[str] = None) -> str:
    """
    Formats a helm chart update notification (HTML)
    :param manual_reason: reason why the update cannot be upgraded from Telegram, if any
    """
    newest = update.newest
    current = update.current

    if update.is_major:
        title = f"Major helm chart update: {chart.name}"
        version_line = f"Version: {update.current_version} -> {newest.version} (major)"
    else:
        title = f"New helm chart version: {chart.name}"
        version_line = f"Version: {update.current_version} -> {newest.version}"

    lines = [
        f"<b>{html.escape(title)}</b>",
        f"Release: {html.escape(chart.name)}",
        f"Namespace: {html.escape(chart.target_namespace or chart.namespace)}",
        f"Chart: {html.escape(chart.chart)} ({html.escape(chart.repo)})",
        html.escape(version_line),
    ]

    current_app_version = current.app_version if current is not None else None
    if newest.app_version and newest.app_version != current_app_version:
        lines.append(html.escape(f"App version: {current_app_version or '?'} -> {newest.app_version}"))

    if update.is_major:
        major = update.current_version.lstrip("v").split(".")[0]
        if update.newest_in_major is not None:
            in_major = update.newest_in_major
            text = f"Newest {major}.x version: {in_major.version}"
            if in_major.app_version and in_major.app_version != current_app_version:
                text += f" (app version {in_major.app_version})"
            lines.append(html.escape(text))
        else:
            lines.append(html.escape(f"No newer {major}.x version available."))
        lines.append("Major updates need manual steps (CRDs, upgrade notes), "
                     "upgrade them by changing the HelmChart manifest.")
    elif manual_reason is not None:
        lines.append(html.escape(f"Upgrade by changing the HelmChart manifest: {manual_reason}."))

    lines.extend(_chart_version_details_to_lines(newest, show_version=update.is_major))
    return "\n".join(lines)


def _chart_version_details_to_lines(version: ChartVersion, show_version: bool) -> List[str]:
    lines = []
    suffix = f" ({html.escape(version.version)})" if show_version else ""
    if len(version.changes) > 0:
        lines.append(f"Changes{suffix}:")
        for change in version.changes[:HELM_CHART_CHANGES_LIMIT]:
            if len(change) > HELM_CHART_CHANGE_LENGTH_LIMIT:
                change = change[:HELM_CHART_CHANGE_LENGTH_LIMIT - 3] + "..."
            lines.append(f"- {html.escape(change)}")
        if len(version.changes) > HELM_CHART_CHANGES_LIMIT:
            lines.append(f"- ... ({len(version.changes) - HELM_CHART_CHANGES_LIMIT} more)")
    if len(version.links) > 0:
        links = " | ".join(
            f'<a href="{html.escape(url, quote=True)}">{html.escape(name)}</a>' for name, url in version.links)
        lines.append(f"Links{suffix}: {links}")
    return lines


def helm_chart_check_result_to_str(result: HelmChartCheckResult, ignored: bool = False) -> str:
    """
    Formats the check result of a single HelmChart as a list entry (HTML)
    :param result: check result
    :param ignored: whether the newest version was ignored
    """
    chart = result.chart
    header = f"> <b>{html.escape(chart.name)}</b> ({html.escape(chart.target_namespace or chart.namespace)})"
    if result.skip_reason is not None:
        version = f"{chart.version}, " if chart.version else ""
        return f"{header}\n  {html.escape(version)}skipped: {html.escape(result.skip_reason.value)}"
    if result.error is not None:
        return f"{header}\n  {html.escape(chart.version)}, error: {html.escape(result.error)}"

    latest = result.latest.version if result.latest is not None else "?"
    line = f"  Current: {chart.version}, latest: {latest}"
    if result.update is not None:
        if result.update.is_major:
            line += " (major)"
            if result.update.newest_in_major is not None:
                line += f", newest in major: {result.update.newest_in_major.version}"
        if ignored:
            line += " (ignored)"
    else:
        line += " (up to date)"
    return f"{header}\n{html.escape(line)}"

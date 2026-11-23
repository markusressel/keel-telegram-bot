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
from keel_telegram_bot.client.poll_result import PollResult
from keel_telegram_bot.client.resource import Resource
from keel_telegram_bot.client.tracked_image import TrackedImage
from keel_telegram_bot.config import Config
from keel_telegram_bot.const import BUTTON_DATA_POLL, BUTTON_DATA_POLL_PREFIX, TELEGRAM_CALLBACK_DATA_LIMIT
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


def approval_signature(data: Approval) -> str:
    """
    :return: what the buttons and the votes of an approval notification show. It leaves out the remaining time of
    the deadline, which changes all the time, so it tells when a message has to be edited and when not.
    """
    return f"{int(data.archived)}|{int(data.rejected)}|{data.votesReceived}/{data.votesRequired}"


def approval_button_data(action: str, approval_id: str) -> str:
    """
    Button data that carries the approval id, so a button does not depend on the text of its message.
    Telegram allows 64 bytes, a Keel approval id is a 36 character UUID.
    :param action: BUTTON_DATA_APPROVE or BUTTON_DATA_REJECT
    """
    return f"{action}:{approval_id}"


def parse_approval_button_data(data: str) -> Tuple[Optional[str], Optional[str]]:
    """
    :return: the action and the approval id of a button. The id is None for the buttons of older messages
    (plain "a" and "r"), their approval is in the text of the message.
    """
    action, _, approval_id = data.partition(":")
    return action, (approval_id or None)


def resource_identifier(identifier: str) -> str:
    """
    :return: the resource identifier of an approval identifier, which ends with the new version,
    f.ex. "deployment/default/myapp" for "deployment/default/myapp:1.2.3"
    """
    name, _, version = identifier.rpartition(":")
    if name and "/" not in version:
        return name
    return identifier


def _approval_event_repository(data: Approval) -> dict:
    event = data.event
    if isinstance(event, dict) and isinstance(event.get("repository"), dict):
        return event["repository"]
    return {}


def approval_new_digest(data: Approval) -> Optional[str]:
    """
    :return: the digest of the image an approval offers, None if unknown. Keel leaves the "digest" of an
    approval empty, the poll trigger puts it into the repository of the event that created the approval.
    """
    digest = data.digest or _approval_event_repository(data).get("digest")
    return digest or None


def approval_repository(data: Approval) -> Optional[str]:
    """
    :return: the image repository of an approval (from the event that created it), f.ex. "ghcr.io/me/app",
    None if unknown
    """
    name = _approval_event_repository(data).get("name")
    return image_repository(name) if name else None


DIGEST_PATTERN = re.compile(r"^[a-z0-9]+(?:[.+_-][a-z0-9]+)*:[a-zA-Z0-9=_-]{32,}$")


def parse_image_id(image_id: Optional[str]) -> Optional[str]:
    """
    :return: the digest of the imageID of a container status, which comes in runtime specific forms
    ("docker-pullable://repo@sha256:...", "repo@sha256:...", "sha256:..."), None if it has none
    """
    if not image_id:
        return None
    if "://" in image_id:
        image_id = image_id.split("://", 1)[1]
    image_id = image_id.rsplit("@", 1)[-1]
    return image_id if DIGEST_PATTERN.match(image_id) else None


def poll_button_data(identifier: str) -> str:
    """
    Data of the "Check now" button. The identifier is left out if it does not fit into the 64 bytes that
    Telegram allows, the button handler then takes it from the message.
    :param identifier: resource identifier
    """
    data = BUTTON_DATA_POLL_PREFIX + identifier
    if len(data.encode("utf-8")) > TELEGRAM_CALLBACK_DATA_LIMIT:
        return BUTTON_DATA_POLL
    return data


def poll_result_to_str(result: PollResult) -> str:
    """
    One line of a poll result
    """
    if result.error:
        return f"{result.image}: error: {result.error}"
    if result.submitted:
        tag = f" ({result.tag})" if result.tag else ""
        return f"{result.image}: newer version found{tag}, update or approval follows"
    return f"{result.image}: up to date"


def poll_results_to_str(results: List[PollResult], target: Optional[str] = None) -> str:
    """
    Summary of a poll. For a single resource every image is listed; for a poll of all images only the images
    with a newer version or an error, plus the number of images that are up to date.
    :param results: results of the poll
    :param target: the polled resource or image, None for a poll of all images
    """
    if target is not None:
        if len(results) == 0:
            return f"Polled {target}: no images"
        if len(results) == 1:
            return f"Polled {target}:\n{poll_result_to_str(results[0])}"
        return "\n".join([f"Polled {target}:"] + [poll_result_to_str(x) for x in results])

    if len(results) == 0:
        return "Polled all images: nothing is watched by the poll trigger"
    found = [x for x in results if x.submitted and not x.error]
    errors = [x for x in results if x.error]
    up_to_date = len(results) - len(found) - len(errors)
    counts = [f"{len(found)} newer"]
    if len(errors) > 0:
        counts.append(f"{len(errors)} failed")
    counts.append(f"{up_to_date} up to date")
    lines = [f"Polled {len(results)} images: {', '.join(counts)}"]
    lines.extend(poll_result_to_str(x) for x in found + errors)
    return "\n".join(lines)


def image_repository(image: str) -> str:
    """
    :return: the repository of an image reference without tag, digest and the implicit Docker Hub parts,
    f.ex. "memcached" for "docker.io/library/memcached:1.6"
    """
    image = image.split("@", 1)[0]
    name, _, tag = image.rpartition(":")
    if name and "/" not in tag:
        image = name
    for prefix in ("index.docker.io/", "docker.io/", "registry-1.docker.io/"):
        if image.startswith(prefix):
            image = image[len(prefix):]
            break
    if image.startswith("library/"):
        image = image[len("library/"):]
    return image


def approval_to_str(data: Approval, detailed: bool = False) -> str:
    """
    :param data: the approval
    :param detailed: True to show all properties, False for the short form used in notifications
    """
    # Keel formats the deadline in UTC, show it in the local time zone (TZ environment variable)
    deadline = data.deadline.astimezone()
    now = datetime.now().replace(microsecond=0).astimezone()
    deadline_diff = timedelta(seconds=(deadline.replace(microsecond=0) - now).total_seconds())

    deadline_abs_str = deadline.strftime('%m/%d %H:%M:%S')
    deadline_remaining_str = deadline_diff_to_str(deadline_diff)
    versions = f"{data.currentVersion} -> {data.newVersion}"

    if detailed:
        return "\n".join([
            f"<b>{html.escape(data.message)}</b>",
            f"Id: {data.id}",
            f"Identifier: {data.identifier}",
            f"Version: {versions}",
            f"Votes: {data.votesReceived}/{data.votesRequired}",
            f"Expires: {deadline_abs_str} ({deadline_remaining_str})"
        ])

    title = html.escape(data.message)
    if data.currentVersion not in data.message or data.newVersion not in data.message:
        title += f" ({html.escape(versions)})"
    lines = [f"<b>{title}</b>"]
    if data.votesRequired > 1 or data.votesReceived > 0:
        lines.append(f"Votes: {data.votesReceived}/{data.votesRequired}")
    lines.append(f"Expires: {deadline_abs_str} ({deadline_remaining_str})")
    return "\n".join(lines)


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


def helm_chart_auto_upgrade_to_str(chart: HelmChart, update: HelmChartUpdate, target: ChartVersion) -> str:
    """
    Formats the notification of an automatic helm chart upgrade (HTML)
    :param chart: the HelmChart, still with the version before the upgrade
    :param update: the update the upgrade belongs to
    :param target: the version the chart is upgraded to
    """
    current = update.current
    lines = [
        f"<b>{html.escape(f'Automatic helm chart upgrade: {chart.name}')}</b>",
        f"Release: {html.escape(chart.name)}",
        f"Namespace: {html.escape(chart.target_namespace or chart.namespace)}",
        f"Chart: {html.escape(chart.chart)} ({html.escape(chart.repo)})",
        html.escape(f"Version: {update.current_version} -> {target.version}"),
    ]
    current_app_version = current.app_version if current is not None else None
    if target.app_version and target.app_version != current_app_version:
        lines.append(html.escape(f"App version: {current_app_version or '?'} -> {target.app_version}"))
    lines.extend(_chart_version_details_to_lines(target, show_version=False))
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

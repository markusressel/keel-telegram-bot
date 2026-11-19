import json
import logging
import os
import threading
from typing import List, Dict

from keel_telegram_bot.helm.version import SemVer

LOGGER = logging.getLogger(__name__)

KEY_CHARTS = "charts"
KEY_ANNOUNCED = "announced"
KEY_IGNORED = "ignored"
KEY_UPGRADES = "upgrades"


class HelmChartState:
    """
    Remembers which chart versions were already announced or ignored, persisted as a small JSON file:

    {"charts": {"<helmchart name>": {"announced": ["1.2.3"], "ignored": ["2.0.0"]}},
     "upgrades": [{"name": "<helmchart name>", "version": "1.2.3", "chat_id": 1, "message_id": 2}]}

    "upgrades" are the upgrades started from Telegram whose outcome was not reported yet. After a restart of the bot
    the notification of such an upgrade would show "Upgrading to ..." forever, so these are picked up again.
    """

    def __init__(self, path: str):
        self._path = path
        self._lock = threading.RLock()
        self._data = self._load()

    def should_announce(self, name: str, versions: List[str]) -> bool:
        """
        :param name: HelmChart name
        :param versions: versions offered in a notification
        :return: true if at least one of the versions was neither announced nor ignored yet
        """
        with self._lock:
            entry = self._get_entry(name)
            known = set(entry[KEY_ANNOUNCED]) | set(entry[KEY_IGNORED])
            return any(version not in known for version in versions)

    def is_ignored(self, name: str, version: str) -> bool:
        with self._lock:
            return version in self._get_entry(name)[KEY_IGNORED]

    def mark_announced(self, name: str, versions: List[str]):
        self._add(name, KEY_ANNOUNCED, versions)

    def ignore(self, name: str, versions: List[str]):
        self._add(name, KEY_IGNORED, versions)

    def prune(self, name: str, current_version: str):
        """
        Forgets all versions that are not newer than the current version of a chart
        :param name: HelmChart name
        :param current_version: currently installed chart version
        """
        current = SemVer.parse(current_version)
        if current is None:
            return

        def is_newer(version: str) -> bool:
            parsed = SemVer.parse(version)
            return parsed is not None and parsed > current

        with self._lock:
            charts = self._data[KEY_CHARTS]
            entry = charts.get(name)
            if entry is None:
                return
            pruned = {key: [x for x in entry.get(key, []) if is_newer(x)] for key in (KEY_ANNOUNCED, KEY_IGNORED)}
            if pruned == {key: entry.get(key, []) for key in (KEY_ANNOUNCED, KEY_IGNORED)}:
                return
            if any(pruned.values()):
                charts[name] = pruned
            else:
                charts.pop(name)
            self._save()

    def add_pending_upgrade(self, name: str, version: str, chat_id: int, message_id: int):
        """
        Remembers an upgrade that was started from a notification message and is not finished yet
        """
        with self._lock:
            self.remove_pending_upgrade(chat_id, message_id, save=False)
            self._data[KEY_UPGRADES].append(
                {"name": name, "version": version, "chat_id": chat_id, "message_id": message_id})
            self._save()

    def remove_pending_upgrade(self, chat_id: int, message_id: int, save: bool = True):
        with self._lock:
            upgrades = self._data[KEY_UPGRADES]
            remaining = [x for x in upgrades if not (x.get("chat_id") == chat_id and x.get("message_id") == message_id)]
            if len(remaining) != len(upgrades):
                self._data[KEY_UPGRADES] = remaining
                if save:
                    self._save()

    def pending_upgrades(self) -> List[Dict]:
        """
        :return: the upgrades that were started and not finished, as dicts with name, version, chat_id and message_id
        """
        with self._lock:
            return [dict(x) for x in self._data[KEY_UPGRADES]]

    def _add(self, name: str, key: str, versions: List[str]):
        with self._lock:
            entry = self._data[KEY_CHARTS].setdefault(name, {KEY_ANNOUNCED: [], KEY_IGNORED: []})
            values = entry.setdefault(key, [])
            new_values = [x for x in versions if x not in values]
            if len(new_values) == 0:
                return
            values.extend(new_values)
            self._save()

    def _get_entry(self, name: str) -> Dict[str, List[str]]:
        entry = self._data[KEY_CHARTS].get(name, {})
        return {
            KEY_ANNOUNCED: entry.get(KEY_ANNOUNCED, []),
            KEY_IGNORED: entry.get(KEY_IGNORED, []),
        }

    def _load(self) -> dict:
        if not os.path.exists(self._path):
            return {KEY_CHARTS: {}, KEY_UPGRADES: []}
        try:
            with open(self._path, "r") as file:
                data = json.load(file)
            if not isinstance(data, dict) or not isinstance(data.get(KEY_CHARTS), dict):
                raise ValueError("unexpected content")
            if not isinstance(data.get(KEY_UPGRADES), list):
                data[KEY_UPGRADES] = []
            return data
        except Exception as ex:
            LOGGER.error(f"Cannot read helm chart state file '{self._path}', starting with an empty state: {ex}")
            return {KEY_CHARTS: {}, KEY_UPGRADES: []}

    def _save(self):
        try:
            directory = os.path.dirname(os.path.abspath(self._path))
            os.makedirs(directory, exist_ok=True)
            # write to a temporary file first, so a crash never leaves a half written state file behind
            tmp_path = f"{self._path}.tmp"
            with open(tmp_path, "w") as file:
                # the key of the upgrades is only written when there are any, which keeps the file as it was
                data = {key: value for key, value in self._data.items() if key != KEY_UPGRADES or value}
                json.dump(data, file, indent=2, sort_keys=True)
            os.replace(tmp_path, self._path)
        except Exception as ex:
            LOGGER.error(f"Cannot write helm chart state file '{self._path}': {ex}")

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
KEY_FAILED = "failed"


class HelmChartState:
    """
    Remembers which chart versions were already announced or ignored, and which upgrades failed,
    persisted as a small JSON file:

    {"charts": {"<helmchart name>": {"announced": ["1.2.3"], "ignored": ["2.0.0"], "failed": ["1.2.2"]}}}
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

    def is_failed(self, name: str, version: str) -> bool:
        """
        :return: true if an upgrade to this version failed (or its outcome is unknown) before
        """
        with self._lock:
            return version in self._get_entry(name)[KEY_FAILED]

    def mark_failed(self, name: str, version: str):
        """
        Remembers that an upgrade to this version failed, so it is never upgraded automatically again
        """
        self._add(name, KEY_FAILED, [version])

    def prune(self, name: str, current_version: str):
        """
        Forgets all versions that are not newer than the current version of a chart. Failed versions are only
        forgotten once the current version is newer: the version of a failed upgrade stays in spec.version, and
        after resetting the chart to an older version it must not be upgraded automatically again.
        :param name: HelmChart name
        :param current_version: currently installed chart version
        """
        current = SemVer.parse(current_version)
        if current is None:
            return

        def is_newer(version: str) -> bool:
            parsed = SemVer.parse(version)
            return parsed is not None and parsed > current

        def is_not_older(version: str) -> bool:
            parsed = SemVer.parse(version)
            return parsed is not None and parsed >= current

        keep = {KEY_ANNOUNCED: is_newer, KEY_IGNORED: is_newer, KEY_FAILED: is_not_older}

        with self._lock:
            charts = self._data[KEY_CHARTS]
            entry = charts.get(name)
            if entry is None:
                return
            pruned = {key: [x for x in entry.get(key, []) if predicate(x)] for key, predicate in keep.items()}
            if pruned == {key: entry.get(key, []) for key in keep}:
                return
            # keep files of older versions free of empty lists
            pruned = {key: value for key, value in pruned.items() if value or key != KEY_FAILED}
            if any(pruned.values()):
                charts[name] = pruned
            else:
                charts.pop(name)
            self._save()

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
            KEY_FAILED: entry.get(KEY_FAILED, []),
        }

    def _load(self) -> dict:
        if not os.path.exists(self._path):
            return {KEY_CHARTS: {}}
        try:
            with open(self._path, "r") as file:
                data = json.load(file)
            if not isinstance(data, dict) or not isinstance(data.get(KEY_CHARTS), dict):
                raise ValueError("unexpected content")
            return data
        except Exception as ex:
            LOGGER.error(f"Cannot read helm chart state file '{self._path}', starting with an empty state: {ex}")
            return {KEY_CHARTS: {}}

    def _save(self):
        try:
            directory = os.path.dirname(os.path.abspath(self._path))
            os.makedirs(directory, exist_ok=True)
            # write to a temporary file first, so a crash never leaves a half written state file behind
            tmp_path = f"{self._path}.tmp"
            with open(tmp_path, "w") as file:
                json.dump(self._data, file, indent=2, sort_keys=True)
            os.replace(tmp_path, self._path)
        except Exception as ex:
            LOGGER.error(f"Cannot write helm chart state file '{self._path}': {ex}")

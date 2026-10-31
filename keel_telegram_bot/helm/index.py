import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import requests
import yaml

from keel_telegram_bot.helm.version import SemVer

LOGGER = logging.getLogger(__name__)

# index files of big repositories are several MB, reading them can take longer than a usual API response
INDEX_REQUESTS_TIMEOUT = (5, 30)

# matches release asset urls of charts published with chart-releaser
GITHUB_RELEASE_ASSET_PATTERN = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/releases/download/([^/]+)/")

try:
    _YamlLoader = yaml.CSafeLoader
except AttributeError:  # pragma: no cover
    _YamlLoader = yaml.SafeLoader


@dataclass
class ChartVersion:
    """
    A single chart version entry of a helm repository index
    """
    version: str
    semver: SemVer
    app_version: Optional[str] = None
    # (name, url) pairs
    links: List[Tuple[str, str]] = field(default_factory=list)
    # changelog entries from the "artifacthub.io/changes" annotation
    changes: List[str] = field(default_factory=list)

    @staticmethod
    def from_dict(data: dict) -> Optional["ChartVersion"]:
        """
        :param data: an entry of the "entries" list in an index.yaml
        :return: the parsed entry, or None if its version is not a semantic version
        """
        version = str(data.get("version", ""))
        semver = SemVer.parse(version)
        if semver is None:
            return None
        annotations = data.get("annotations", {}) or {}
        app_version = data.get("appVersion")
        return ChartVersion(
            version=version,
            semver=semver,
            app_version=str(app_version) if app_version is not None else None,
            links=_parse_links(data, annotations),
            changes=_parse_changes(annotations.get("artifacthub.io/changes")),
        )


@dataclass
class HelmChartUpdate:
    """
    Newer versions of a chart found in its repository
    """
    current_version: str
    # the chart version entry of the current version, if the index still contains it
    current: Optional[ChartVersion]
    # newest version overall
    newest: ChartVersion
    # newest version with the same major version as the current one, if it is newer than the current one
    newest_in_major: Optional[ChartVersion]

    @property
    def is_major(self) -> bool:
        return self.newest.semver.major != SemVer.parse(self.current_version).major

    @property
    def offered_versions(self) -> List[str]:
        """
        :return: all versions mentioned in the update notification
        """
        result = [self.newest.version]
        if self.newest_in_major is not None and self.newest_in_major.version != self.newest.version:
            result.append(self.newest_in_major.version)
        return result


def fetch_index(repo: str) -> dict:
    """
    Downloads and parses the index.yaml of a helm repository
    :param repo: repository url
    :return: parsed index
    """
    url = f"{repo.rstrip('/')}/index.yaml"
    LOGGER.debug(f"Fetching helm repository index: {url}")
    response = requests.get(url, timeout=INDEX_REQUESTS_TIMEOUT)
    response.raise_for_status()
    return parse_index(response.content)


def parse_index(content: bytes | str) -> dict:
    """
    Parses the content of an index.yaml
    :param content: file content
    :return: parsed index
    """
    data = yaml.load(content, Loader=_YamlLoader)
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        raise ValueError("Invalid helm repository index: missing 'entries'")
    return data


def get_chart_versions(index: dict, chart: str) -> List[ChartVersion]:
    """
    :param index: parsed index
    :param chart: chart name
    :return: all versions of the given chart with a semantic version, newest first
    """
    entries = index["entries"].get(chart)
    if entries is None:
        raise KeyError(f"Chart '{chart}' not found in repository index")
    result = []
    for entry in entries:
        version = ChartVersion.from_dict(entry)
        if version is None:
            LOGGER.debug(f"Ignoring non-semver version '{entry.get('version')}' of chart '{chart}'")
            continue
        result.append(version)
    return sorted(result, key=lambda x: x.semver, reverse=True)


def find_update(current_version: str, versions: List[ChartVersion]) -> Optional[HelmChartUpdate]:
    """
    Finds newer versions of a chart. Pre-releases are only considered if the current version is a pre-release itself.
    :param current_version: currently installed chart version
    :param versions: available chart versions
    :return: the update, or None if there is no newer version
    """
    current = SemVer.parse(current_version)
    if current is None:
        raise ValueError(f"Current version '{current_version}' is not a semantic version")

    candidates = [
        x for x in versions
        if x.semver > current and (current.is_prerelease or not x.semver.is_prerelease)
    ]
    if len(candidates) == 0:
        return None

    newest = max(candidates, key=lambda x: x.semver)
    same_major = [x for x in candidates if x.semver.major == current.major]
    newest_in_major = max(same_major, key=lambda x: x.semver) if same_major else None
    current_entry = next((x for x in versions if x.semver == current), None)

    return HelmChartUpdate(
        current_version=current_version,
        current=current_entry,
        newest=newest,
        newest_in_major=newest_in_major,
    )


def _parse_links(data: dict, annotations: dict) -> List[Tuple[str, str]]:
    links = []

    urls = data.get("urls", []) or []
    for url in urls:
        match = GITHUB_RELEASE_ASSET_PATTERN.match(str(url))
        if match is not None:
            owner, repo, tag = match.groups()
            links.append(("Release", f"https://github.com/{owner}/{repo}/releases/tag/{tag}"))
            break

    artifacthub_links = annotations.get("artifacthub.io/links")
    if artifacthub_links:
        try:
            for item in yaml.load(artifacthub_links, Loader=_YamlLoader) or []:
                if isinstance(item, dict) and item.get("url"):
                    links.append((str(item.get("name") or "Link"), str(item["url"])))
        except yaml.YAMLError as ex:
            LOGGER.debug(f"Ignoring invalid artifacthub.io/links annotation: {ex}")

    sources = data.get("sources", []) or []
    if len(sources) > 0:
        links.append(("Source", str(sources[0])))

    home = data.get("home")
    if home:
        links.append(("Home", str(home)))

    # remove duplicate urls, keeping the first name
    result = []
    seen = set()
    for name, url in links:
        if url not in seen:
            seen.add(url)
            result.append((name, url))
    return result


def _parse_changes(changes) -> List[str]:
    """
    Parses the "artifacthub.io/changes" annotation, which is either a list of strings
    or a list of objects with "kind" and "description"
    """
    if not changes:
        return []
    try:
        items = yaml.load(changes, Loader=_YamlLoader) if isinstance(changes, str) else changes
    except yaml.YAMLError as ex:
        LOGGER.debug(f"Ignoring invalid artifacthub.io/changes annotation: {ex}")
        return []
    if not isinstance(items, list):
        return []

    result = []
    for item in items:
        if isinstance(item, dict):
            description = item.get("description")
            if not description:
                continue
            kind = item.get("kind")
            result.append(f"{kind}: {description}" if kind else str(description))
        elif item:
            result.append(str(item))
    return result

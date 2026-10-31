import logging
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from keel_telegram_bot.helm import index
from keel_telegram_bot.helm.chart import HelmChart, SkipReason
from keel_telegram_bot.helm.client import HelmChartClient
from keel_telegram_bot.helm.index import ChartVersion, HelmChartUpdate
from keel_telegram_bot.helm.version import SemVer

LOGGER = logging.getLogger(__name__)


@dataclass
class HelmChartCheckResult:
    """
    Result of an update check of a single HelmChart
    """
    chart: HelmChart
    # newest version available in the repository (respecting the pre-release rule)
    latest: Optional[ChartVersion] = None
    update: Optional[HelmChartUpdate] = None
    skip_reason: Optional[SkipReason] = None
    error: Optional[str] = None


class HelmChartUpdateChecker:
    """
    Checks HelmChart objects for newer chart versions in their repositories
    """

    def __init__(self, client: HelmChartClient, allow: List[str] = None, deny: List[str] = None,
                 fetch_index: Callable[[str], dict] = index.fetch_index):
        self._client = client
        self._allow = allow or []
        self._deny = deny or []
        self._fetch_index = fetch_index

    def check(self) -> List[HelmChartCheckResult]:
        """
        Lists all HelmCharts and checks each of them for updates. This method blocks.
        :return: one result per HelmChart
        """
        charts = self._client.list_helm_charts()
        # several charts often share a repository, fetch each index only once per check
        index_cache: Dict[str, dict | Exception] = {}
        return [self._check_chart(chart, index_cache) for chart in charts]

    def _check_chart(self, chart: HelmChart, index_cache: Dict[str, dict | Exception]) -> HelmChartCheckResult:
        skip_reason = chart.get_skip_reason(self._allow, self._deny)
        if skip_reason is not None:
            if skip_reason == SkipReason.OCI:
                LOGGER.info(f"Skipping HelmChart '{chart.name}': {skip_reason.value} ({chart.chart})")
            else:
                LOGGER.debug(f"Skipping HelmChart '{chart.name}': {skip_reason.value}")
            return HelmChartCheckResult(chart=chart, skip_reason=skip_reason)

        try:
            if chart.repo not in index_cache:
                try:
                    index_cache[chart.repo] = self._fetch_index(chart.repo)
                except Exception as ex:
                    index_cache[chart.repo] = ex
            repo_index = index_cache[chart.repo]
            if isinstance(repo_index, Exception):
                raise repo_index

            versions = index.get_chart_versions(repo_index, chart.chart)
            current = SemVer.parse(chart.version)
            if current is None:
                raise ValueError(f"Current version '{chart.version}' is not a semantic version")
            considered = [x for x in versions if current.is_prerelease or not x.semver.is_prerelease]
            latest = max(considered, key=lambda x: x.semver) if considered else None
            update = index.find_update(chart.version, versions)
            return HelmChartCheckResult(chart=chart, latest=latest, update=update)
        except Exception as ex:
            LOGGER.warning(f"Cannot check HelmChart '{chart.name}' for updates: {ex}")
            return HelmChartCheckResult(chart=chart, error=str(ex))

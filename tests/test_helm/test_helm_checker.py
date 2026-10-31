from unittest.mock import Mock

from keel_telegram_bot.helm.chart import HelmChart, SkipReason
from keel_telegram_bot.helm.checker import HelmChartUpdateChecker
from keel_telegram_bot.helm.client import HelmChartClient
from keel_telegram_bot.helm.index import parse_index
from tests import TestBase

INDEX = parse_index("""
entries:
  loki:
  - version: 20.3.0
  - version: 20.2.0
  - version: 21.0.0-rc.1
  alloy:
  - version: 1.15.0
""")


def _chart(name, version="1.0.0", repo="https://charts.example.com", chart=None):
    return HelmChart(name=name, namespace="kube-system", chart=chart or name, repo=repo, version=version,
                     target_namespace=name)


class HelmChartCheckerTest(TestBase):

    def test_check(self):
        client = Mock(spec=HelmChartClient)
        client.list_helm_charts.return_value = [
            _chart("loki", "20.2.0"),
            _chart("alloy", "1.15.0"),
            _chart("tempo"),
            _chart("ocichart", chart="oci://ghcr.io/foo/bar", repo=None),
            _chart("denied"),
        ]
        fetch_index = Mock(return_value=INDEX)
        checker = HelmChartUpdateChecker(client, deny=["denied"], fetch_index=fetch_index)

        results = {x.chart.name: x for x in checker.check()}

        # the index of a repository is only fetched once per check
        fetch_index.assert_called_once_with("https://charts.example.com")

        self.assertEqual("20.3.0", results["loki"].update.newest.version)
        self.assertEqual("20.3.0", results["loki"].latest.version)
        self.assertIsNone(results["alloy"].update)
        self.assertEqual("1.15.0", results["alloy"].latest.version)
        self.assertIn("tempo", results["tempo"].error)
        self.assertEqual(SkipReason.OCI, results["ocichart"].skip_reason)
        self.assertEqual(SkipReason.FILTERED, results["denied"].skip_reason)

    def test_check_index_error(self):
        client = Mock(spec=HelmChartClient)
        client.list_helm_charts.return_value = [_chart("loki", "20.2.0"), _chart("alloy", "1.15.0")]
        fetch_index = Mock(side_effect=IOError("connection refused"))
        checker = HelmChartUpdateChecker(client, fetch_index=fetch_index)

        results = checker.check()

        fetch_index.assert_called_once()
        self.assertEqual(["connection refused", "connection refused"], [x.error for x in results])

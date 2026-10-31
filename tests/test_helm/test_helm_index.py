from keel_telegram_bot.helm.index import parse_index, get_chart_versions, find_update
from keel_telegram_bot.util import helm_chart_update_to_str
from keel_telegram_bot.helm.chart import HelmChart
from tests import TestBase

INDEX = """
apiVersion: v1
entries:
  loki:
  - apiVersion: v2
    appVersion: 3.8.0
    name: loki
    version: 20.3.0
    home: https://grafana-community.github.io/helm-charts
    sources:
    - https://github.com/grafana/loki
    urls:
    - https://github.com/grafana-community/helm-charts/releases/download/loki-20.3.0/loki-20.3.0.tgz
    annotations:
      artifacthub.io/changes: |
        - kind: fixed
          description: "Fix <ingress> & stuff"
        - kind: added
          description: New option
      artifacthub.io/links: |
        - name: Upgrade Guide
          url: https://example.com/upgrade
        - name: Chart Source
          url: https://github.com/grafana/loki
  - appVersion: 3.7.9
    name: loki
    version: 20.2.0
  - appVersion: 4.0.0-rc.1
    name: loki
    version: 21.0.0-rc.1
  - name: loki
    version: not-a-version
  alloy:
  - appVersion: v1.11.0
    name: alloy
    version: 1.15.0
    annotations:
      artifacthub.io/changes: |
        - Plain text change
generated: "2026-10-30T00:00:00Z"
"""


class HelmIndexTest(TestBase):

    def test_parse_index(self):
        index = parse_index(INDEX)
        versions = get_chart_versions(index, "loki")
        # non-semver versions are dropped, newest first
        self.assertEqual(["21.0.0-rc.1", "20.3.0", "20.2.0"], [x.version for x in versions])

        newest = versions[1]
        self.assertEqual("3.8.0", newest.app_version)
        self.assertEqual(["fixed: Fix <ingress> & stuff", "added: New option"], newest.changes)
        self.assertEqual([
            ("Release", "https://github.com/grafana-community/helm-charts/releases/tag/loki-20.3.0"),
            ("Upgrade Guide", "https://example.com/upgrade"),
            ("Chart Source", "https://github.com/grafana/loki"),
            ("Home", "https://grafana-community.github.io/helm-charts"),
        ], newest.links)

        alloy = get_chart_versions(index, "alloy")[0]
        self.assertEqual(["Plain text change"], alloy.changes)
        self.assertEqual([], alloy.links)

    def test_parse_index_missing_chart(self):
        index = parse_index(INDEX)
        with self.assertRaises(KeyError):
            get_chart_versions(index, "tempo")

    def test_parse_index_invalid(self):
        with self.assertRaises(ValueError):
            parse_index("foo: bar")

    def test_update_format(self):
        index = parse_index(INDEX)
        chart = HelmChart(name="loki", namespace="kube-system", chart="loki",
                          repo="https://grafana-community.github.io/helm-charts", version="20.2.0",
                          target_namespace="loki")
        update = find_update(chart.version, get_chart_versions(index, "loki"))
        text = helm_chart_update_to_str(chart, update)

        self.assertIn("Release: loki\n", text)
        self.assertIn("Version: 20.2.0 -&gt; 20.3.0", text)
        self.assertIn("App version: 3.7.9 -&gt; 3.8.0", text)
        self.assertIn("- fixed: Fix &lt;ingress&gt; &amp; stuff", text)
        self.assertIn('<a href="https://example.com/upgrade">Upgrade Guide</a>', text)
        self.assertNotIn("major", text)

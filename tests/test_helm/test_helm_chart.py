from keel_telegram_bot.helm.chart import HelmChart, SkipReason
from tests import TestBase


def _chart(name="loki", annotations=None, **spec):
    return HelmChart.from_dict({
        "metadata": {"name": name, "namespace": "kube-system", "annotations": annotations or {}},
        "spec": spec,
        "status": {"jobName": f"helm-install-{name}"},
    })


class HelmChartTest(TestBase):

    def test_from_dict(self):
        chart = _chart(chart="loki", repo="https://grafana-community.github.io/helm-charts", version="20.2.0",
                       targetNamespace="loki")
        self.assertEqual("loki", chart.name)
        self.assertEqual("20.2.0", chart.version)
        self.assertEqual("helmchart/loki/loki", chart.identifier)
        self.assertEqual("helm-install-loki", chart.install_job_name)
        self.assertIsNone(chart.get_skip_reason())

    def test_k3s_addon(self):
        # bundled traefik, as deployed by k3s
        chart = _chart(name="traefik", annotations={
            "objectset.rio.cattle.io/owner-gvk": "k3s.cattle.io/v1, Kind=Addon",
            "objectset.rio.cattle.io/owner-name": "traefik",
        }, chart="https://%{KUBERNETES_API}%/static/charts/traefik-39.0.0.tgz")
        self.assertTrue(chart.is_k3s_managed)
        self.assertEqual(SkipReason.K3S_MANAGED, chart.get_skip_reason())

    def test_k3s_static_chart_without_annotation(self):
        chart = _chart(name="gateway-api-crd",
                       chart="https://%{KUBERNETES_API}%/static/charts/gateway-api-crd-1.6.103.tgz")
        self.assertTrue(chart.is_k3s_managed)
        self.assertEqual(SkipReason.K3S_MANAGED, chart.get_skip_reason())

    def test_not_k3s_managed(self):
        chart = _chart(annotations={"objectset.rio.cattle.io/owner-gvk": "helm.cattle.io/v1, Kind=HelmChart"},
                       chart="traefik", repo="https://traefik.github.io/charts", version="39.0.0")
        self.assertFalse(chart.is_k3s_managed)
        self.assertIsNone(chart.get_skip_reason())

    def test_skip_reasons(self):
        self.assertEqual(SkipReason.NO_REPO, _chart(chart="https://example.com/x.tgz").get_skip_reason())
        self.assertEqual(SkipReason.NO_VERSION, _chart(chart="loki", repo="https://x").get_skip_reason())
        self.assertEqual(SkipReason.OCI, _chart(chart="oci://ghcr.io/foo/bar", version="1.0.0").get_skip_reason())

    def test_allow_deny(self):
        chart = _chart(chart="loki", repo="https://x", version="1.0.0")
        self.assertIsNone(chart.get_skip_reason(allow=["loki"]))
        self.assertEqual(SkipReason.FILTERED, chart.get_skip_reason(allow=["alloy"]))
        self.assertEqual(SkipReason.FILTERED, chart.get_skip_reason(deny=["loki"]))
        self.assertIsNone(chart.get_skip_reason(allow=[], deny=["alloy"]))

import enum
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List

import yaml

LOGGER = logging.getLogger(__name__)

ANNOTATION_OWNER_GVK = "objectset.rio.cattle.io/owner-gvk"
K3S_ADDON_GVK = "k3s.cattle.io/v1, Kind=Addon"
K3S_STATIC_CHART_MARKER = "%{KUBERNETES_API}%"

# Charts that ship CRDs, which helm does not upgrade, and the value that makes the chart upgrade them
# itself. Without this value set to true, an upgrade needs manual steps and is not offered from Telegram.
CRD_UPGRADE_VALUES = {
    "kube-prometheus-stack": "crds.upgradeJob.enabled",
}


class SkipReason(enum.Enum):
    """
    Reasons for a HelmChart not being checked for updates
    """
    K3S_MANAGED = "managed by k3s"
    NO_REPO = "no spec.repo"
    NO_VERSION = "no spec.version"
    OCI = "OCI repositories are not supported"
    FILTERED = "excluded by allow/deny list"


@dataclass
class HelmChart:
    """
    A HelmChart object (helm.cattle.io/v1) of the k3s helm-controller
    """
    name: str
    namespace: str
    chart: Optional[str]
    repo: Optional[str]
    version: Optional[str]
    target_namespace: Optional[str]
    job_name: Optional[str] = None
    annotations: Dict[str, str] = field(default_factory=dict)
    values_content: Optional[str] = None
    set_values: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_dict(data: dict) -> "HelmChart":
        metadata = data.get("metadata", {}) or {}
        spec = data.get("spec", {}) or {}
        status = data.get("status", {}) or {}
        return HelmChart(
            name=metadata["name"],
            namespace=metadata.get("namespace"),
            chart=spec.get("chart"),
            repo=spec.get("repo"),
            version=spec.get("version"),
            target_namespace=spec.get("targetNamespace"),
            job_name=status.get("jobName"),
            annotations=metadata.get("annotations", {}) or {},
            values_content=spec.get("valuesContent"),
            set_values=spec.get("set", {}) or {},
        )

    @property
    def identifier(self) -> str:
        """
        Identifier used for the per-chat filters, similar to keel resource identifiers
        """
        return f"helmchart/{self.target_namespace or self.namespace}/{self.name}"

    @property
    def install_job_name(self) -> str:
        """
        Name of the Job the helm-controller uses to install/upgrade this chart
        """
        return self.job_name or f"helm-install-{self.name}"

    @property
    def is_k3s_managed(self) -> bool:
        """
        :return: true if this HelmChart is managed (and upgraded) by k3s itself, f.ex. the bundled traefik
        """
        owner_gvk = self.annotations.get(ANNOTATION_OWNER_GVK, "")
        if owner_gvk.startswith(K3S_ADDON_GVK):
            return True
        return K3S_STATIC_CHART_MARKER in (self.chart or "") or K3S_STATIC_CHART_MARKER in (self.repo or "")

    @property
    def is_oci(self) -> bool:
        return (self.chart or "").startswith("oci://") or (self.repo or "").startswith("oci://")

    def get_value(self, path: str) -> Any:
        """
        Looks up a chart value set in the HelmChart, spec.set takes precedence over spec.valuesContent
        (like --set over --values). Values from spec.valuesSecrets or the chart defaults are not known.
        :param path: dotted value path, f.ex. "crds.upgradeJob.enabled"
        :return: the value, or None if it is not set
        """
        if path in self.set_values:
            return self.set_values[path]
        try:
            node = yaml.safe_load(self.values_content or "")
        except yaml.YAMLError as ex:
            LOGGER.warning(f"Cannot parse valuesContent of HelmChart '{self.name}': {ex}")
            return None
        for key in path.split("."):
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        return node

    def get_manual_upgrade_reason(self, notify_only: List[str] = None) -> Optional[str]:
        """
        Determines whether updates of this chart are only announced, without an upgrade from Telegram
        :param notify_only: names of HelmCharts whose updates are only announced
        :return: the reason, or None if minor and patch updates can be upgraded from Telegram
        """
        if notify_only and self.name in notify_only:
            return "listed in helm_charts.notify_only"
        chart_name = (self.chart or "").rstrip("/").split("/")[-1]
        crd_value = CRD_UPGRADE_VALUES.get(chart_name)
        if crd_value is not None and str(self.get_value(crd_value)).lower() != "true":
            return f"the chart does not upgrade its CRDs ({crd_value} is not true)"
        return None

    def get_skip_reason(self, allow: List[str] = None, deny: List[str] = None) -> Optional[SkipReason]:
        """
        Determines whether this chart should be skipped when checking for updates
        :param allow: if not empty, only charts with one of these names are checked
        :param deny: charts with one of these names are never checked
        :return: the reason to skip this chart, or None if it should be checked
        """
        if allow and self.name not in allow:
            return SkipReason.FILTERED
        if deny and self.name in deny:
            return SkipReason.FILTERED
        if self.is_k3s_managed:
            return SkipReason.K3S_MANAGED
        if self.is_oci:
            return SkipReason.OCI
        if not self.repo:
            return SkipReason.NO_REPO
        if not self.version:
            return SkipReason.NO_VERSION
        return None

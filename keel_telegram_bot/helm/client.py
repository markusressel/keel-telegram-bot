import enum
import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional

from kubernetes import client, config
from kubernetes.client import ApiException, V1Job, V1Pod
from kubernetes.config import ConfigException

from keel_telegram_bot.helm.chart import HelmChart

LOGGER = logging.getLogger(__name__)

HELM_CHART_GROUP = "helm.cattle.io"
HELM_CHART_VERSION = "v1"
HELM_CHART_PLURAL = "helmcharts"

# env variable of the helm-controller install job container, holding the chart version it installs
JOB_ENV_VERSION = "VERSION"
JOB_LOG_TAIL_LINES = 20


class InstallJobStatus(enum.Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class InstallJobResult:
    status: InstallJobStatus
    message: str
    log_tail: Optional[str] = None


class HelmChartClient:
    """
    Kubernetes API client for HelmChart objects of the k3s helm-controller and their install jobs
    """

    def __init__(self, namespace: str):
        self._namespace = namespace
        self._custom_objects_api = None
        self._batch_api = None
        self._core_api = None

    def _ensure_initialized(self):
        if self._custom_objects_api is not None:
            return
        try:
            config.load_incluster_config()
        except ConfigException:
            LOGGER.debug("Not running in a cluster, falling back to kubeconfig")
            config.load_kube_config()
        self._custom_objects_api = client.CustomObjectsApi()
        self._batch_api = client.BatchV1Api()
        self._core_api = client.CoreV1Api()

    def list_helm_charts(self) -> List[HelmChart]:
        """
        :return: all HelmChart objects in the configured namespace
        """
        self._ensure_initialized()
        response = self._custom_objects_api.list_namespaced_custom_object(
            HELM_CHART_GROUP, HELM_CHART_VERSION, self._namespace, HELM_CHART_PLURAL)
        items = [HelmChart.from_dict(item) for item in response.get("items", [])]
        return sorted(items, key=lambda x: x.name)

    def get_helm_chart(self, name: str) -> HelmChart:
        self._ensure_initialized()
        response = self._custom_objects_api.get_namespaced_custom_object(
            HELM_CHART_GROUP, HELM_CHART_VERSION, self._namespace, HELM_CHART_PLURAL, name)
        return HelmChart.from_dict(response)

    def set_version(self, name: str, version: str) -> HelmChart:
        """
        Sets spec.version of a HelmChart, which makes the helm-controller run "helm upgrade" in its install job
        :param name: HelmChart name
        :param version: new chart version
        :return: the patched HelmChart
        """
        self._ensure_initialized()
        response = self._custom_objects_api.patch_namespaced_custom_object(
            HELM_CHART_GROUP, HELM_CHART_VERSION, self._namespace, HELM_CHART_PLURAL, name,
            body={"spec": {"version": version}},
            _content_type="application/merge-patch+json",
        )
        return HelmChart.from_dict(response)

    def wait_for_install_job(self, chart: HelmChart, version: str, timeout: timedelta,
                             poll_interval: float = 5) -> InstallJobResult:
        """
        Waits until the install job of the given chart version succeeded or failed. This method blocks.
        :param chart: the HelmChart
        :param version: chart version the job should install
        :param timeout: maximum time to wait
        :param poll_interval: seconds between status checks
        :return: result
        """
        self._ensure_initialized()
        job_name = chart.install_job_name
        deadline = time.monotonic() + timeout.total_seconds()
        job = None
        while True:
            job = self._get_job(job_name)
            # the helm-controller replaces the job of the previous version, ignore it until then
            if job is not None and _get_job_version(job) == version:
                result = self._evaluate_job(job)
                if result is not None:
                    return result

            if time.monotonic() >= deadline:
                break
            time.sleep(poll_interval)

        log_tail = None
        if job is not None and _get_job_version(job) == version:
            message = f"Job {self._namespace}/{job_name} did not finish within {timeout}"
            pods = self._get_job_pods(job)
            if len(pods) > 0:
                log_tail = self._get_log_tail(pods[-1], previous=False)
        else:
            message = f"Job {self._namespace}/{job_name} for version {version} was not created within {timeout}"
        return InstallJobResult(InstallJobStatus.TIMEOUT, message, log_tail)

    def _evaluate_job(self, job: V1Job) -> Optional[InstallJobResult]:
        """
        :return: the result of a finished job, or None if it is still running
        """
        job_name = job.metadata.name
        for condition in (job.status.conditions or []) if job.status else []:
            if condition.status != "True":
                continue
            if condition.type == "Complete":
                return InstallJobResult(InstallJobStatus.SUCCEEDED, f"Job {self._namespace}/{job_name} succeeded")
            if condition.type == "Failed":
                pods = self._get_job_pods(job)
                log_tail = self._get_log_tail(pods[-1], previous=False) if pods else None
                return InstallJobResult(
                    InstallJobStatus.FAILED,
                    f"Job {self._namespace}/{job_name} failed: {condition.reason}: {condition.message}",
                    log_tail)

        # the install job retries failed attempts many times (restartPolicy OnFailure, high backoffLimit),
        # so the first failed attempt is reported as failure instead of waiting for the job to give up
        for pod in self._get_job_pods(job):
            for container_status in (pod.status.container_statuses or []) if pod.status else []:
                terminated = container_status.state.terminated if container_status.state else None
                if terminated is not None and terminated.exit_code != 0:
                    return InstallJobResult(
                        InstallJobStatus.FAILED,
                        f"Job {self._namespace}/{job_name} failed: container exited with code {terminated.exit_code}",
                        self._get_log_tail(pod, previous=False))
                if container_status.restart_count and container_status.restart_count > 0:
                    return InstallJobResult(
                        InstallJobStatus.FAILED,
                        f"Job {self._namespace}/{job_name} failed: container restarted "
                        f"{container_status.restart_count} time(s), the helm-controller keeps retrying",
                        self._get_log_tail(pod, previous=True))
        return None

    def _get_job(self, name: str) -> Optional[V1Job]:
        try:
            return self._batch_api.read_namespaced_job(name, self._namespace)
        except ApiException as ex:
            if ex.status == 404:
                return None
            raise

    def _get_job_pods(self, job: V1Job) -> List[V1Pod]:
        """
        :return: pods of the given job, oldest first
        """
        response = self._core_api.list_namespaced_pod(
            self._namespace, label_selector=f"batch.kubernetes.io/controller-uid={job.metadata.uid}")
        return sorted(response.items, key=lambda x: x.metadata.creation_timestamp)

    def _get_log_tail(self, pod: V1Pod, previous: bool) -> Optional[str]:
        try:
            return self._core_api.read_namespaced_pod_log(
                pod.metadata.name, self._namespace, tail_lines=JOB_LOG_TAIL_LINES, previous=previous)
        except ApiException as ex:
            LOGGER.warning(f"Cannot read log of pod {self._namespace}/{pod.metadata.name}: {ex.reason}")
            return None


def _get_job_version(job: V1Job) -> Optional[str]:
    """
    :return: the chart version the given install job installs
    """
    try:
        containers = job.spec.template.spec.containers
    except AttributeError:
        return None
    for container in containers or []:
        for env in container.env or []:
            if env.name == JOB_ENV_VERSION:
                return env.value
    return None

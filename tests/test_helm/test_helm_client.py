from datetime import timedelta, datetime, timezone
from unittest.mock import Mock

from kubernetes.client import V1Job, V1PodList, V1Pod, ApiException

from keel_telegram_bot.helm.chart import HelmChart
from keel_telegram_bot.helm.client import HelmChartClient, InstallJobStatus
from tests import TestBase

CHART = HelmChart(name="loki", namespace="kube-system", chart="loki", repo="https://x", version="20.2.0",
                  target_namespace="loki")


def _job(version: str, conditions=None, uid="job-uid") -> V1Job:
    return V1Job.from_dict({
        "metadata": {"name": "helm-install-loki", "uid": uid},
        "spec": {"template": {"spec": {"containers": [
            {"name": "helm", "env": [{"name": "NAME", "value": "loki"}, {"name": "VERSION", "value": version}]}
        ]}}},
        "status": {"conditions": conditions or []},
    })


def _pod(restart_count=0, terminated_exit_code=None) -> V1Pod:
    state = {"running": {}} if terminated_exit_code is None else {"terminated": {"exitCode": terminated_exit_code}}
    return V1Pod.from_dict({
        "metadata": {"name": "helm-install-loki-abcde", "creationTimestamp": datetime.now(timezone.utc).isoformat()},
        "status": {"containerStatuses": [{
            "name": "helm", "image": "rancher/klipper-helm", "imageID": "", "ready": False,
            "restartCount": restart_count, "state": state,
        }]},
    })


def _client(jobs, pods=None, log="Error: UPGRADE FAILED"):
    client = HelmChartClient("kube-system")
    client._custom_objects_api = Mock()
    client._batch_api = Mock()
    client._batch_api.read_namespaced_job.side_effect = jobs
    client._core_api = Mock()
    client._core_api.list_namespaced_pod.return_value = V1PodList(items=pods or [])
    client._core_api.read_namespaced_pod_log.return_value = log
    return client


class HelmChartClientTest(TestBase):

    def test_set_version(self):
        client = _client([])
        client._custom_objects_api.patch_namespaced_custom_object.return_value = {
            "metadata": {"name": "loki", "namespace": "kube-system"}, "spec": {"version": "20.3.0"}}

        chart = client.set_version("loki", "20.3.0")

        self.assertEqual("20.3.0", chart.version)
        args, kwargs = client._custom_objects_api.patch_namespaced_custom_object.call_args
        self.assertEqual(("helm.cattle.io", "v1", "kube-system", "helmcharts", "loki"), args)
        self.assertEqual({"spec": {"version": "20.3.0"}}, kwargs["body"])
        self.assertEqual("application/merge-patch+json", kwargs["_content_type"])

    def test_wait_success(self):
        complete = [{"type": "Complete", "status": "True"}]
        client = _client([
            ApiException(status=404),
            # job of the previous version, already complete
            _job("20.2.0", complete),
            _job("20.3.0"),
            _job("20.3.0", complete),
        ])

        result = client.wait_for_install_job(CHART, "20.3.0", timedelta(minutes=1), poll_interval=0)

        self.assertEqual(InstallJobStatus.SUCCEEDED, result.status)
        self.assertEqual(4, client._batch_api.read_namespaced_job.call_count)

    def test_wait_failed_restart(self):
        client = _client([_job("20.3.0")], pods=[_pod(restart_count=1)])

        result = client.wait_for_install_job(CHART, "20.3.0", timedelta(minutes=1), poll_interval=0)

        self.assertEqual(InstallJobStatus.FAILED, result.status)
        self.assertEqual("Error: UPGRADE FAILED", result.log_tail)
        _, kwargs = client._core_api.read_namespaced_pod_log.call_args
        self.assertTrue(kwargs["previous"])
        _, kwargs = client._core_api.list_namespaced_pod.call_args
        self.assertEqual("batch.kubernetes.io/controller-uid=job-uid", kwargs["label_selector"])

    def test_wait_failed_exit_code(self):
        client = _client([_job("20.3.0")], pods=[_pod(terminated_exit_code=1)])

        result = client.wait_for_install_job(CHART, "20.3.0", timedelta(minutes=1), poll_interval=0)

        self.assertEqual(InstallJobStatus.FAILED, result.status)
        _, kwargs = client._core_api.read_namespaced_pod_log.call_args
        self.assertFalse(kwargs["previous"])

    def test_wait_failed_condition(self):
        client = _client([_job("20.3.0", [{"type": "Failed", "status": "True", "reason": "BackoffLimitExceeded",
                                           "message": "Job has reached the specified backoff limit"}])])

        result = client.wait_for_install_job(CHART, "20.3.0", timedelta(minutes=1), poll_interval=0)

        self.assertEqual(InstallJobStatus.FAILED, result.status)
        self.assertIn("BackoffLimitExceeded", result.message)

    def test_wait_timeout(self):
        client = _client([_job("20.2.0")])

        result = client.wait_for_install_job(CHART, "20.3.0", timedelta(seconds=0), poll_interval=0)

        self.assertEqual(InstallJobStatus.TIMEOUT, result.status)
        self.assertIn("was not created", result.message)

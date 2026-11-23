import logging
import os
from typing import Optional, Set

from kubernetes import client, config
from kubernetes.config import ConfigException

from keel_telegram_bot.util import image_repository, parse_image_id

LOGGER = logging.getLogger(__name__)

SERVICE_ACCOUNT_NAMESPACE_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"


def running_digests_of_pod(pod, repositories: Set[str]) -> Set[str]:
    """
    :param pod: a V1Pod
    :param repositories: image repositories (see image_repository()) of the containers to look at
    :return: the digests of the images that the running containers of these repositories were started from
    """
    images = {x.name: x.image for x in (pod.spec.containers or [])}
    result = set()
    for status in (pod.status.container_statuses or []) if pod.status is not None else []:
        image = images.get(status.name)
        if image is None or image_repository(image) not in repositories:
            continue
        # a waiting container has not pulled anything yet, its imageID is empty or left over from before
        if status.state is not None and status.state.waiting is not None:
            continue
        digest = parse_image_id(status.image_id)
        if digest is not None:
            result.add(digest)
    return result


class SelfPodClient:
    """
    Reads the pod the bot runs in from the Kubernetes API, to tell which image Keel (a container in the same
    pod) runs. The pod is found by POD_NAME and POD_NAMESPACE (downward API) or else by HOSTNAME (the pod name
    by default) and the namespace of the ServiceAccount. Needs "get" on pods in that namespace.
    """

    def __init__(self, pod_name: Optional[str] = None, namespace: Optional[str] = None):
        self._pod_name = pod_name or os.environ.get("POD_NAME") or os.environ.get("HOSTNAME")
        self._namespace = namespace or os.environ.get("POD_NAMESPACE") or self._read_namespace()
        self._core_api = None

    @staticmethod
    def _read_namespace() -> Optional[str]:
        try:
            with open(SERVICE_ACCOUNT_NAMESPACE_FILE) as file:
                return file.read().strip() or None
        except OSError:
            return None

    def _ensure_initialized(self):
        if self._core_api is not None:
            return
        try:
            config.load_incluster_config()
        except ConfigException:
            LOGGER.debug("Not running in a cluster, falling back to kubeconfig")
            config.load_kube_config()
        self._core_api = client.CoreV1Api()

    def running_digests(self, repositories: Set[str]) -> Optional[Set[str]]:
        """
        :param repositories: image repositories of the containers to look at
        :return: the digests the matching containers of this pod run, None if they cannot be determined
        """
        if not self._pod_name or not self._namespace or len(repositories) == 0:
            return None
        try:
            self._ensure_initialized()
            pod = self._core_api.read_namespaced_pod(self._pod_name, self._namespace)
        except Exception as ex:
            LOGGER.warning(f"Cannot read pod {self._namespace}/{self._pod_name} to find the running image of "
                           f"Keel: {ex}")
            return None
        digests = running_digests_of_pod(pod, repositories)
        return digests or None

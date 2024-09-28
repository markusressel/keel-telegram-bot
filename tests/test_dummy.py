from keel_telegram_bot.client import parse_golang_duration, timedelta_to_golang_duration
from keel_telegram_bot.client.approval import Approval
from keel_telegram_bot.client.resource import Resource
from keel_telegram_bot.util import approval_to_str, resource_to_str
from tests import TestBase


class DummyTest(TestBase):

    def test_dummy(self):
        self.assertTrue(True)

    def test_parse_golang_duration(self):
        duration = parse_golang_duration("24h")
        print(duration)

        golang_duration_str = timedelta_to_golang_duration(duration)
        print(golang_duration_str)


    def test_approval_format(self):
        approval = Approval.from_dict({
            "id": "48d6da3e-e4c9-4d12-8562-b7975e805d80",
            "identifier": "deployment/local-path-storage/local-path-provisioner:v0.0.19",
            "currentVersion": "v0.0.17",
            "newVersion": "v0.0.19",
            "votesRequired": 1,
            "votesReceived": 0,
            "deadline": "2020-12-18 23:16:14.811933+00:00",
            "message": "New image is available for resource local-path-storage/local-path-provisioner (v0.0.17 -> v0.0.19).",
            "provider": "kubernetes",
            "event": "image_update",
            "digest": "sha256:3b4f4b3",
            "archived": False,
            "voters": [
                "user1",
            ],
            "rejected": False,
            "createdAt": "2020-12-11 23:16:14.811933+00:00",
            "updatedAt": "2020-12-11 23:16:14.811933+00:00",
        })

        result = approval_to_str(approval)
        print(result)

    def test_resource_format(self):
        resource = Resource.from_dict({
            "provider": "kubernetes",
            "identifier": "statefulset/py-image-dedup/deduplicator",
            "name": "deduplicator",
            "namespace": "py-image-dedup",
            "kind": "statefulset",
            "policy": "semver",
            "images": [
                "codeberg.org/forgejo/forgejo:1.21.11-0",
                "library/memcached:1.6.31"
            ],
            "labels": {
                "workload.user.cattle.io/workloadselector": "statefulSet-py-image-dedup-deduplicator",
            },
            "annotations": {
                "keel.sh/approvals": 1,
                "keel.sh/policy": "major",
                "keel.sh/pollSchedule": "@every 24h",
                "keel.sh/trigger": "poll",
            },
            "status": {
                "replicas": 1,
                "updatedReplicas": 1,
                "readyReplicas": 1,
                "availableReplicas": 1,
                "unavailableReplicas": 0,
            }
        })

        result = resource_to_str(resource)
        print("")
        print(result)

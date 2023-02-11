from keel_telegram_bot.util import approval_to_str
from tests import TestBase


class DummyTest(TestBase):

    def test_dummy(self):
        self.assertTrue(True)

    def test_approval_format(self):
        approval = {
            "id": "48d6da3e-e4c9-4d12-8562-b7975e805d80",
            "identifier": "deployment/local-path-storage/local-path-provisioner:v0.0.19",
            "currentVersion": "v0.0.17",
            "newVersion": "v0.0.19",
            "votesRequired": 1,
            "votesReceived": 0,
            "deadline": "2020-12-18 23:16:14.811933+00:00",
            "message": "New image is available for resource local-path-storage/local-path-provisioner (v0.0.17 -> v0.0.19).",
        }

        result = approval_to_str(approval)
        print(result)

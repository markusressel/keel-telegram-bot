import json
import os
import tempfile

from keel_telegram_bot.helm.state import HelmChartState
from tests import TestBase


class HelmChartStateTest(TestBase):

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._dir.name, "data", "state.json")

    def tearDown(self):
        self._dir.cleanup()

    def test_announce_once(self):
        state = HelmChartState(self.path)
        self.assertTrue(state.should_announce("loki", ["20.3.0"]))
        state.mark_announced("loki", ["20.3.0"])
        self.assertFalse(state.should_announce("loki", ["20.3.0"]))
        # a newer version is announced again
        self.assertTrue(state.should_announce("loki", ["20.4.0"]))
        # other charts are independent
        self.assertTrue(state.should_announce("alloy", ["20.3.0"]))

    def test_announce_if_any_version_is_new(self):
        state = HelmChartState(self.path)
        state.mark_announced("prometheus", ["93.0.0", "92.17.0"])
        self.assertFalse(state.should_announce("prometheus", ["93.0.0", "92.17.0"]))
        self.assertTrue(state.should_announce("prometheus", ["93.0.0", "92.18.0"]))

    def test_ignore(self):
        state = HelmChartState(self.path)
        state.ignore("loki", ["21.0.0"])
        self.assertTrue(state.is_ignored("loki", "21.0.0"))
        self.assertFalse(state.is_ignored("loki", "21.0.1"))
        self.assertFalse(state.should_announce("loki", ["21.0.0"]))
        self.assertTrue(state.should_announce("loki", ["21.0.1"]))

    def test_persistence(self):
        state = HelmChartState(self.path)
        state.mark_announced("loki", ["20.3.0"])
        state.ignore("loki", ["21.0.0"])

        reloaded = HelmChartState(self.path)
        self.assertFalse(reloaded.should_announce("loki", ["20.3.0"]))
        self.assertTrue(reloaded.is_ignored("loki", "21.0.0"))
        with open(self.path) as file:
            self.assertEqual({"charts": {"loki": {"announced": ["20.3.0"], "ignored": ["21.0.0"]}}}, json.load(file))

    def test_prune(self):
        state = HelmChartState(self.path)
        state.mark_announced("loki", ["20.3.0", "21.0.0"])
        state.ignore("loki", ["20.3.0"])

        state.prune("loki", "20.3.0")
        self.assertFalse(state.is_ignored("loki", "20.3.0"))
        self.assertFalse(state.should_announce("loki", ["21.0.0"]))

        state.prune("loki", "21.0.0")
        with open(self.path) as file:
            self.assertEqual({"charts": {}}, json.load(file))

    def test_corrupt_file(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as file:
            file.write("{not json")
        state = HelmChartState(self.path)
        self.assertTrue(state.should_announce("loki", ["20.3.0"]))


class HelmChartStatePendingUpgradeTest(TestBase):

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._dir.name, "state.json")

    def tearDown(self):
        self._dir.cleanup()

    def test_pending_upgrade_survives_restart(self):
        state = HelmChartState(self.path)
        state.add_pending_upgrade("loki", "20.3.0", 123, 7)

        self.assertEqual([{"name": "loki", "version": "20.3.0", "chat_id": 123, "message_id": 7}],
                         HelmChartState(self.path).pending_upgrades())

    def test_remove_pending_upgrade(self):
        state = HelmChartState(self.path)
        state.add_pending_upgrade("loki", "20.3.0", 123, 7)
        state.add_pending_upgrade("alloy", "1.16.0", 123, 8)
        state.remove_pending_upgrade(123, 7)

        self.assertEqual(["alloy"], [x["name"] for x in HelmChartState(self.path).pending_upgrades()])

    def test_same_message_is_only_listed_once(self):
        state = HelmChartState(self.path)
        state.add_pending_upgrade("loki", "20.3.0", 123, 7)
        state.add_pending_upgrade("loki", "20.4.0", 123, 7)

        self.assertEqual(["20.4.0"], [x["version"] for x in state.pending_upgrades()])

    def test_file_without_pending_upgrades_is_unchanged(self):
        state = HelmChartState(self.path)
        state.mark_announced("loki", ["20.3.0"])
        state.add_pending_upgrade("loki", "20.3.0", 123, 7)
        state.remove_pending_upgrade(123, 7)

        with open(self.path) as file:
            self.assertEqual(["charts"], list(json.load(file).keys()))

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

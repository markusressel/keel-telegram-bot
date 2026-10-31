from keel_telegram_bot.helm.index import ChartVersion, find_update
from keel_telegram_bot.helm.version import SemVer
from tests import TestBase


def _versions(*versions: str):
    return [ChartVersion(version=x, semver=SemVer.parse(x)) for x in versions]


class HelmVersionTest(TestBase):

    def test_parse(self):
        self.assertEqual(SemVer(1, 2, 3), SemVer.parse("1.2.3"))
        self.assertEqual(SemVer(1, 2, 3), SemVer.parse("v1.2.3"))
        self.assertEqual(SemVer(1, 2, 0), SemVer.parse("1.2"))
        self.assertEqual(SemVer(1, 2, 3, ("rc", "1")), SemVer.parse("1.2.3-rc.1"))
        self.assertEqual(SemVer(1, 2, 3), SemVer.parse("1.2.3+build.5"))
        self.assertIsNone(SemVer.parse("latest"))
        self.assertIsNone(SemVer.parse("1.2.3.4"))
        self.assertIsNone(SemVer.parse(None))

    def test_order(self):
        self.assertLess(SemVer.parse("1.2.3"), SemVer.parse("1.2.4"))
        self.assertLess(SemVer.parse("1.2.9"), SemVer.parse("1.10.0"))
        self.assertLess(SemVer.parse("1.99.99"), SemVer.parse("2.0.0"))
        self.assertEqual(SemVer.parse("1.2.3+a"), SemVer.parse("1.2.3+b"))

    def test_order_prerelease(self):
        # example from semver.org: 1.0.0-alpha < 1.0.0-alpha.1 < 1.0.0-alpha.beta < 1.0.0-beta
        # < 1.0.0-beta.2 < 1.0.0-beta.11 < 1.0.0-rc.1 < 1.0.0
        ordered = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta",
                   "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"]
        parsed = [SemVer.parse(x) for x in ordered]
        self.assertEqual(parsed, sorted(reversed(parsed)))
        self.assertTrue(SemVer.parse("1.0.0-rc.1").is_prerelease)
        self.assertFalse(SemVer.parse("1.0.0").is_prerelease)

    def test_find_update_none(self):
        self.assertIsNone(find_update("1.2.3", _versions("1.2.3", "1.2.2", "1.0.0")))

    def test_find_update_patch(self):
        update = find_update("1.2.3", _versions("1.2.3", "1.2.4"))
        self.assertFalse(update.is_major)
        self.assertEqual("1.2.4", update.newest.version)
        self.assertEqual("1.2.4", update.newest_in_major.version)
        self.assertEqual("1.2.3", update.current.version)
        self.assertEqual(["1.2.4"], update.offered_versions)

    def test_find_update_minor(self):
        update = find_update("1.2.3", _versions("1.2.3", "1.2.4", "1.3.0"))
        self.assertFalse(update.is_major)
        self.assertEqual("1.3.0", update.newest.version)

    def test_find_update_major(self):
        update = find_update("1.2.3", _versions("1.2.3", "1.3.0", "2.0.0", "2.1.0"))
        self.assertTrue(update.is_major)
        self.assertEqual("2.1.0", update.newest.version)
        self.assertEqual("1.3.0", update.newest_in_major.version)
        self.assertEqual(["2.1.0", "1.3.0"], update.offered_versions)

    def test_find_update_major_only(self):
        update = find_update("1.2.3", _versions("1.2.3", "2.0.0"))
        self.assertTrue(update.is_major)
        self.assertIsNone(update.newest_in_major)
        self.assertEqual(["2.0.0"], update.offered_versions)

    def test_find_update_ignores_prereleases(self):
        update = find_update("1.2.3", _versions("1.2.3", "1.2.4", "1.3.0-rc.1", "2.0.0-beta.1"))
        self.assertEqual("1.2.4", update.newest.version)
        self.assertFalse(update.is_major)
        self.assertIsNone(find_update("1.2.3", _versions("1.2.3", "1.3.0-rc.1")))

    def test_find_update_from_prerelease(self):
        update = find_update("2.0.0-rc.1", _versions("1.9.0", "2.0.0-rc.1", "2.0.0-rc.2"))
        self.assertEqual("2.0.0-rc.2", update.newest.version)
        update = find_update("2.0.0-rc.1", _versions("2.0.0-rc.1", "2.0.0-rc.2", "2.0.0"))
        self.assertEqual("2.0.0", update.newest.version)

    def test_find_update_current_not_in_index(self):
        update = find_update("v1.2.3", _versions("v1.2.4"))
        self.assertIsNone(update.current)
        self.assertEqual("v1.2.4", update.newest.version)

    def test_find_update_invalid_current(self):
        with self.assertRaises(ValueError):
            find_update("latest", _versions("1.0.0"))

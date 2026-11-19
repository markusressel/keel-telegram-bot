import os
import time
from datetime import datetime, timedelta, timezone
from unittest import mock

from keel_telegram_bot.util import approval_to_str, approval_button_data, parse_approval_button_data
from tests import TestBase
from tests.test_approval_messages import _approval


class ApprovalFormatTest(TestBase):

    def setUp(self):
        self._tz = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/Berlin"
        time.tzset()

    def tearDown(self):
        if self._tz is None:
            os.environ.pop("TZ")
        else:
            os.environ["TZ"] = self._tz
        time.tzset()

    def _approval(self, **kwargs):
        approval = _approval(**kwargs)
        approval.message = "New image is available for deployment/ns/app (1.0.0 -> 1.1.0)."
        approval.deadline = datetime(2020, 12, 18, 23, 16, 14, tzinfo=timezone.utc)
        return approval

    def test_short_form(self):
        now = datetime(2020, 12, 18, 11, 0, 0, tzinfo=timezone.utc)
        with mock.patch("keel_telegram_bot.util.datetime") as dt:
            dt.now.return_value = now.replace(tzinfo=None)
            text = approval_to_str(self._approval())
        lines = text.split("\n")
        self.assertEqual("<b>New image is available for deployment/ns/app (1.0.0 -&gt; 1.1.0).</b>", lines[0])
        # 23:16 UTC is 00:16 in Berlin on the next day, without an offset
        self.assertTrue(lines[1].startswith("Expires: 12/19 00:16:14 ("), lines[1])
        self.assertEqual(2, len(lines))
        self.assertNotIn("Id:", text)
        self.assertNotIn("+00:00", text)

    def test_short_form_shows_votes_only_when_they_matter(self):
        self.assertNotIn("Votes", approval_to_str(self._approval(votes=0)))
        multi = self._approval()
        multi.votesRequired = 2
        self.assertIn("Votes: 0/2", approval_to_str(multi))
        self.assertIn("Votes: 1/1", approval_to_str(self._approval(votes=1)))

    def test_versions_are_added_when_the_message_lacks_them(self):
        approval = self._approval()
        approval.message = "New image is available"
        self.assertIn("(1.0.0 -&gt; 1.1.0)", approval_to_str(approval).split("\n")[0])

    def test_detailed_form_has_all_properties(self):
        text = approval_to_str(self._approval(), detailed=True)
        for expected in ["Id: a1", "Identifier: deployment/ns/app:1.1.0", "Version: 1.0.0 -> 1.1.0", "Votes: 0/1",
                         "Expires:"]:
            self.assertIn(expected, text)

    def test_button_data(self):
        uuid = "3e2b6f0e-6a53-4d8a-9c3f-0a1b2c3d4e5f"
        data = approval_button_data("a", uuid)
        self.assertLessEqual(len(data.encode()), 64)
        self.assertEqual(("a", uuid), parse_approval_button_data(data))
        self.assertEqual(("a", None), parse_approval_button_data("a"))

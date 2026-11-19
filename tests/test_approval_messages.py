import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, AsyncMock, MagicMock

from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut

from keel_telegram_bot.bot import KeelTelegramBot, MAX_EDIT_FAILURES
from keel_telegram_bot.bot.message_state import ApprovalMessageState
from keel_telegram_bot.client.api_client import KeelApiClient
from keel_telegram_bot.client.approval import Approval
from keel_telegram_bot.client.types import Provider
from keel_telegram_bot.util import approval_signature
from tests import TestBase

CHAT = 12345678


def _config():
    config = MagicMock()
    config.TELEGRAM_BOT_TOKEN.value = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    config.TELEGRAM_CHAT_IDS.value = [str(CHAT), "-1001"]
    config.TELEGRAM_ADMIN_USERNAMES.value = ["myadminuser"]
    config.TELEGRAM_FILTERS.value = []
    return config


def _approval(id="a1", identifier="deployment/ns/app:1.1.0", archived=False, rejected=False, votes=0) -> Approval:
    now = datetime.now(timezone.utc)
    return Approval(
        id=id, archived=archived, provider=Provider.Kubernetes, identifier=identifier, event="push",
        message="New image is available", currentVersion="1.0.0", newVersion="1.1.0", digest="",
        votesRequired=1, votesReceived=votes, voters=[], rejected=rejected,
        deadline=now + timedelta(hours=23), createdAt=now, updatedAt=now,
    )


class ApprovalMessageStateTest(TestBase):

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._dir.name, "state.json")

    def tearDown(self):
        self._dir.cleanup()

    def test_survives_restart(self):
        state = ApprovalMessageState(self.path)
        state.register(CHAT, 7, "a1", "deployment/ns/app:1.1.0", "0|0|0/1")

        restarted = ApprovalMessageState(self.path)
        messages = restarted.all()
        self.assertEqual(1, len(messages))
        self.assertEqual((CHAT, 7, "a1", "0|0|0/1"),
                         (messages[0].chat_id, messages[0].message_id, messages[0].approval_id,
                          messages[0].signature))

    def test_register_known_message_only_updates_it(self):
        state = ApprovalMessageState(self.path)
        state.register(CHAT, 7, "a1", "x", "old")
        state.register(CHAT, 7, "a1", "x", "new")
        self.assertEqual(["new"], [x.signature for x in state.all()])

    def test_remove(self):
        state = ApprovalMessageState(self.path)
        state.register(CHAT, 7, "a1", "x")
        state.register(CHAT, 8, "a2", "y")
        state.remove(state.find(CHAT, 7))
        self.assertEqual([8], [x.message_id for x in ApprovalMessageState(self.path).all()])

    def test_prune_old_messages(self):
        state = ApprovalMessageState(self.path, max_age=timedelta(days=1))
        state.register(CHAT, 7, "a1", "x")
        self.assertEqual(0, state.prune())
        self.assertEqual(1, state.prune(now=datetime.now(timezone.utc) + timedelta(days=2)))
        self.assertEqual([], state.all())

    def test_broken_file_starts_empty(self):
        with open(self.path, "w") as file:
            file.write("{not json")
        self.assertEqual([], ApprovalMessageState(self.path).all())

    def test_in_memory(self):
        state = ApprovalMessageState()
        state.register(CHAT, 7, "a1", "x")
        self.assertEqual(1, len(state.all()))


class UpdateMessagesTest(TestBase):

    def setUp(self):
        self.api = Mock(spec=KeelApiClient)
        self.state = ApprovalMessageState()
        self.bot = KeelTelegramBot(_config(), self.api, approval_message_state=self.state)
        self.bot._app = Mock()
        self.telegram = Mock()
        self.telegram.edit_message_text = AsyncMock()
        self.telegram.edit_message_reply_markup = AsyncMock()
        self._bot_patch = type(self.bot).bot
        type(self.bot).bot = property(lambda _: self.telegram)

    def tearDown(self):
        type(self.bot).bot = self._bot_patch

    def _register(self, approval: Approval, message_id=7, chat_id=CHAT):
        self.bot._register_message(chat_id, message_id, approval)

    def _update(self):
        asyncio.run(self.bot.update_messages())

    def test_no_edit_when_nothing_changed(self):
        approval = _approval()
        self.api.get_approvals.return_value = [approval]
        self._register(approval)

        self._update()
        self._update()

        self.telegram.edit_message_text.assert_not_called()
        self.assertEqual(1, len(self.state.all()))

    def test_approved_message_shows_outcome_and_is_forgotten(self):
        self._register(_approval())
        self.api.get_approvals.return_value = [_approval(archived=True, votes=1)]

        self._update()

        self.telegram.edit_message_text.assert_called_once()
        menu = self.telegram.edit_message_text.call_args.kwargs["reply_markup"]
        self.assertEqual(["Approved"], [b.text for row in menu.inline_keyboard for b in row])
        self.assertEqual([], self.state.all())

    def test_rejected_message_shows_outcome_and_is_forgotten(self):
        self._register(_approval())
        self.api.get_approvals.return_value = [_approval(rejected=True)]

        self._update()

        menu = self.telegram.edit_message_text.call_args.kwargs["reply_markup"]
        self.assertEqual(["Rejected"], [b.text for row in menu.inline_keyboard for b in row])
        self.assertEqual([], self.state.all())

    def test_votes_change_is_shown_and_message_stays(self):
        self._register(_approval())
        self.api.get_approvals.return_value = [_approval(votes=1)]

        self._update()

        self.telegram.edit_message_text.assert_called_once()
        self.assertEqual(approval_signature(_approval(votes=1)), self.state.all()[0].signature)

    def test_expired_approval_replaces_buttons(self):
        self._register(_approval())
        self.api.get_approvals.return_value = []

        self._update()

        self.telegram.edit_message_text.assert_not_called()
        menu = self.telegram.edit_message_reply_markup.call_args.kwargs["reply_markup"]
        self.assertEqual(["Expired"], [b.text for row in menu.inline_keyboard for b in row])
        self.assertEqual([], self.state.all())

    def test_failure_in_one_chat_does_not_stop_the_others(self):
        self._register(_approval(), message_id=7, chat_id=CHAT)
        self._register(_approval(), message_id=8, chat_id=-1001)
        self.api.get_approvals.return_value = [_approval(archived=True, votes=1)]

        async def edit(text, chat_id, message_id, **kwargs):
            if chat_id == CHAT:
                raise Forbidden("bot was kicked")

        self.telegram.edit_message_text.side_effect = edit

        self._update()

        self.assertEqual(2, self.telegram.edit_message_text.call_count)
        self.assertEqual([], self.state.all())

    def test_not_modified_is_not_a_failure(self):
        self._register(_approval())
        self.api.get_approvals.return_value = [_approval(votes=1)]
        self.telegram.edit_message_text.side_effect = BadRequest("Message is not modified")

        self._update()

        message = self.state.all()[0]
        self.assertEqual(0, message.failures)
        self.assertEqual(approval_signature(_approval(votes=1)), message.signature)

    def test_message_that_cannot_be_edited_is_forgotten(self):
        self._register(_approval())
        self.api.get_approvals.return_value = [_approval(votes=1)]
        self.telegram.edit_message_text.side_effect = BadRequest("Message to edit not found")

        self._update()

        self.assertEqual([], self.state.all())

    def test_temporary_error_is_retried(self):
        self._register(_approval())
        self.api.get_approvals.return_value = [_approval(archived=True, votes=1)]
        self.telegram.edit_message_text.side_effect = TimedOut("timeout")

        self._update()
        self.assertEqual(1, self.state.all()[0].failures)

        self.telegram.edit_message_text.side_effect = None
        self._update()
        self.assertEqual([], self.state.all())

    def test_gives_up_after_repeated_failures(self):
        self._register(_approval())
        self.api.get_approvals.return_value = [_approval(archived=True, votes=1)]
        self.telegram.edit_message_text.side_effect = TimedOut("timeout")

        for _ in range(MAX_EDIT_FAILURES):
            self._update()

        self.assertEqual([], self.state.all())

    def test_rate_limit_keeps_messages_and_stops_the_run(self):
        self._register(_approval("a1"), message_id=7)
        self._register(_approval("a2", "deployment/ns/other:2.0.0"), message_id=8)
        self.api.get_approvals.return_value = [_approval("a1", archived=True, votes=1),
                                               _approval("a2", "deployment/ns/other:2.0.0", archived=True, votes=1)]
        self.telegram.edit_message_text.side_effect = RetryAfter(30)

        self._update()

        self.assertEqual(1, self.telegram.edit_message_text.call_count)
        self.assertEqual(2, len(self.state.all()))

    def test_unknown_message_is_updated_after_a_click(self):
        # a message from before the state existed, registered when its button is pressed
        self.state.register(CHAT, 9, "a1", "deployment/ns/app:1.1.0")
        self.api.get_approvals.return_value = [_approval(archived=True, votes=1)]

        self._update()

        self.assertEqual(9, self.telegram.edit_message_text.call_args.kwargs["message_id"])
        self.assertEqual([], self.state.all())

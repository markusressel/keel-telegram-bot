import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, AsyncMock, MagicMock, patch

from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut

from keel_telegram_bot.bot import KeelTelegramBot, MAX_EDIT_FAILURES
from keel_telegram_bot.db import Store, normalize_url
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


class StoreMessagesTest(TestBase):

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.url = "sqlite:///" + os.path.join(self._dir.name, "sub", "state.db")

    def tearDown(self):
        self._dir.cleanup()

    def test_survives_restart(self):
        Store(self.url).register(CHAT, 7, "a1", "deployment/ns/app:1.1.0", "0|0|0/1")

        messages = Store(self.url).all()
        self.assertEqual(1, len(messages))
        self.assertEqual((CHAT, 7, "a1", "0|0|0/1"),
                         (messages[0].chat_id, messages[0].message_id, messages[0].approval_id,
                          messages[0].signature))

    def test_register_known_message_only_updates_it(self):
        store = Store(self.url)
        store.register(CHAT, 7, "a1", "x", "old")
        store.register(CHAT, 7, "a1", "x", "new")
        self.assertEqual(["new"], [x.signature for x in store.all()])

    def test_remove(self):
        store = Store(self.url)
        store.register(CHAT, 7, "a1", "x")
        store.register(CHAT, 8, "a2", "y")
        store.remove(store.find(CHAT, 7))
        self.assertEqual([8], [x.message_id for x in Store(self.url).all()])

    def test_prune_old_messages(self):
        store = Store(self.url, max_age=timedelta(days=1))
        store.register(CHAT, 7, "a1", "x")
        self.assertEqual(0, store.prune())
        self.assertEqual(1, store.prune(now=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=2)))
        self.assertEqual([], store.all())

    def test_migrating_twice_is_fine(self):
        Store(self.url)
        Store(self.url)

    def test_in_memory(self):
        store = Store()
        store.register(CHAT, 7, "a1", "x")
        self.assertEqual(1, len(store.all()))

    def test_postgres_url_uses_psycopg3(self):
        self.assertEqual("postgresql+psycopg://u:p@h/db", normalize_url("postgresql://u:p@h/db"))
        self.assertEqual("postgresql+psycopg://u:p@h/db", normalize_url("postgres://u:p@h/db"))
        self.assertEqual("sqlite:///x.db", normalize_url("sqlite:///x.db"))


class StoreAnnouncedTest(TestBase):

    def test_announced_per_chat(self):
        store = Store()
        self.assertFalse(store.is_announced("a1", CHAT))
        store.mark_announced("a1", CHAT)
        store.mark_announced("a1", CHAT)
        self.assertTrue(store.is_announced("a1", CHAT))
        self.assertFalse(store.is_announced("a1", 99))

    def test_seed_once(self):
        store = Store()
        self.assertTrue(store.seed_announced(["a1", "a2"], [CHAT, 99]))
        self.assertTrue(store.is_announced("a2", 99))
        self.assertFalse(store.seed_announced(["a3"], [CHAT]))
        self.assertFalse(store.is_announced("a3", CHAT))

    def test_forget_finished_approvals(self):
        store = Store()
        store.mark_announced("a1", CHAT)
        store.mark_announced("a2", CHAT)
        store.forget_announced_except(["a2"])
        self.assertFalse(store.is_announced("a1", CHAT))
        self.assertTrue(store.is_announced("a2", CHAT))
        store.forget_announced_except([])
        self.assertFalse(store.is_announced("a2", CHAT))

    def test_pending_helm_upgrades(self):
        store = Store()
        store.add_pending_upgrade("loki", "1.2.0", CHAT, 7)
        store.add_pending_upgrade("loki", "1.3.0", CHAT, 7)
        pending = store.pending_upgrades()
        self.assertEqual([("loki", "1.3.0", CHAT, 7)],
                         [(x.name, x.version, x.chat_id, x.message_id) for x in pending])
        store.remove_pending_upgrade(CHAT, 7)
        self.assertEqual([], store.pending_upgrades())


class AnnounceTest(TestBase):

    def setUp(self):
        self.store = Store()
        self.bot = KeelTelegramBot(_config(), Mock(spec=KeelApiClient), store=self.store)
        self.bot._app = Mock()
        self.telegram = Mock()
        self._bot_patch = type(self.bot).bot
        type(self.bot).bot = property(lambda _: self.telegram)

    def tearDown(self):
        type(self.bot).bot = self._bot_patch

    def _announce(self, approval, send):
        with patch("keel_telegram_bot.bot.send_message", new=send):
            return asyncio.run(self.bot.on_new_pending_approval(approval))

    def test_announces_once_per_chat_and_remembers_the_message(self):
        send = AsyncMock(side_effect=[Mock(chat_id=CHAT, message_id=5), Mock(chat_id=-1001, message_id=6)])
        self.assertTrue(self._announce(_approval(), send))
        self.assertEqual(2, send.call_count)
        self.assertEqual(2, len(self.store.all()))

        self.assertFalse(self._announce(_approval(), send))
        self.assertEqual(2, send.call_count)

    def test_failed_chat_is_tried_again(self):
        ok = Mock(chat_id=CHAT, message_id=5)
        send = AsyncMock(side_effect=[ok, TimedOut("x")])
        self._announce(_approval(), send)
        self.assertTrue(self.store.is_announced("a1", CHAT))
        self.assertFalse(self.store.is_announced("a1", -1001))

        send = AsyncMock(return_value=Mock(chat_id=-1001, message_id=6))
        self.assertTrue(self._announce(_approval(), send))
        self.assertEqual(1, send.call_count)


class UpdateMessagesTest(TestBase):

    def setUp(self):
        self.api = Mock(spec=KeelApiClient)
        self.state = Store()
        self.bot = KeelTelegramBot(_config(), self.api, store=self.state)
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
        self.assertEqual(["Expired", "Check now"], [b.text for row in menu.inline_keyboard for b in row])
        self.assertEqual("p:deployment/ns/app", menu.inline_keyboard[1][0].callback_data)
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

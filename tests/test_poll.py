import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch

import requests
from telegram import Update, Message
from telegram.ext import CallbackContext

from keel_telegram_bot.bot import KeelTelegramBot
from keel_telegram_bot.client.api_client import KeelApiClient
from keel_telegram_bot.client.poll_result import PollResult, PollBusyError, PollNotWatchedError, \
    PollUnsupportedError
from keel_telegram_bot.client.resource import Resource
from keel_telegram_bot.const import POLL_REQUESTS_TIMEOUT
from keel_telegram_bot.db import Store
from keel_telegram_bot.util import poll_results_to_str, resource_identifier, poll_button_data, image_repository
from tests import TestBase
from tests.test_approval_messages import _approval

CHAT = 12345678
ADMIN = "myadminuser"


def _config(filters=None):
    config = MagicMock()
    config.TELEGRAM_BOT_TOKEN.value = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    config.TELEGRAM_CHAT_IDS.value = [str(CHAT)]
    config.TELEGRAM_ADMIN_USERNAMES.value = [ADMIN]
    config.TELEGRAM_FILTERS.value = filters or []
    return config


def _resource(identifier: str, images) -> Resource:
    kind, namespace, name = identifier.split("/")
    return Resource.from_dict({
        "provider": "kubernetes", "identifier": identifier, "name": name, "namespace": namespace, "kind": kind,
        "policy": "minor", "images": images, "labels": {}, "annotations": {},
        "status": {"replicas": 1, "updatedReplicas": 1, "readyReplicas": 1, "availableReplicas": 1,
                   "unavailableReplicas": 0},
    })


def _response(status: int, body: bytes, content_type="application/json") -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = body
    response.headers["Content-Type"] = content_type
    response.url = "http://keel:9300/v1/poll"
    return response


class PollClientTest(TestBase):

    def setUp(self):
        self.client = KeelApiClient("keel", 9300, False, "user", "password")

    def _poll(self, response: requests.Response, **kwargs):
        with patch("requests.sessions.Session.request", return_value=response) as request:
            return self.client.poll(**kwargs), request

    def test_poll_all(self):
        body = (b'{"results": [{"image": "ghcr.io/a/b", "submitted": true, "error": "", "tag": "1.2.0"},'
                b'{"image": "library/redis", "submitted": false, "error": ""},'
                b'{"image": "x/y", "submitted": false, "error": "unauthorized", "tag": ""}]}')
        results, request = self._poll(_response(200, body))

        self.assertEqual([
            PollResult("ghcr.io/a/b", True, "", "1.2.0"),
            PollResult("library/redis", False, "", None),
            PollResult("x/y", False, "unauthorized", None),
        ], results)
        kwargs = request.call_args.kwargs
        self.assertEqual(("post", "http://keel:9300/v1/poll"), (kwargs["method"].lower(), kwargs["url"]))
        self.assertEqual({}, kwargs["json"])
        self.assertEqual(POLL_REQUESTS_TIMEOUT, kwargs["timeout"])
        self.assertGreater(POLL_REQUESTS_TIMEOUT[1], 60)
        self.assertIsNotNone(kwargs["auth"])

    def test_poll_identifier_and_image(self):
        _, request = self._poll(_response(200, b'{"results": []}'), identifier="deployment/ns/app")
        self.assertEqual({"identifier": "deployment/ns/app"}, request.call_args.kwargs["json"])

        _, request = self._poll(_response(200, b'{"results": []}'), image="ghcr.io/a/b")
        self.assertEqual({"image": "ghcr.io/a/b"}, request.call_args.kwargs["json"])

        with self.assertRaises(ValueError):
            self.client.poll(identifier="deployment/ns/app", image="ghcr.io/a/b")

    def test_not_watched(self):
        with self.assertRaises(PollNotWatchedError) as ex:
            self._poll(_response(404, b'{"error": "not watched by the poll trigger"}'), identifier="d/ns/app")
        self.assertEqual("not watched by the poll trigger", str(ex.exception))

    def test_endpoint_missing(self):
        with self.assertRaises(PollUnsupportedError):
            self._poll(_response(404, b"404 page not found\n", "text/plain"))
        with self.assertRaises(PollUnsupportedError):
            self._poll(_response(405, b""))

    def test_busy(self):
        with self.assertRaises(PollBusyError):
            self._poll(_response(429, b'{"error": "a poll of all images is running"}'))

    def test_other_errors(self):
        with self.assertRaises(requests.HTTPError):
            self._poll(_response(500, b'{"error": "boom"}'))


class PollFormatTest(TestBase):

    def test_resource_identifier(self):
        self.assertEqual("deployment/ns/app", resource_identifier("deployment/ns/app:1.2.3"))
        self.assertEqual("deployment/ns/app", resource_identifier("deployment/ns/app"))

    def test_button_data(self):
        self.assertEqual("p:deployment/ns/app", poll_button_data("deployment/ns/app"))
        self.assertEqual("p", poll_button_data("deployment/" + "n" * 40 + "/" + "a" * 40))

    def test_image_repository(self):
        self.assertEqual("memcached", image_repository("docker.io/library/memcached:1.6"))
        self.assertEqual("memcached", image_repository("memcached"))
        self.assertEqual("ghcr.io/a/b", image_repository("ghcr.io/a/b@sha256:abc"))
        self.assertEqual("registry:5000/a", image_repository("registry:5000/a:1.0"))

    def test_single(self):
        self.assertEqual("Polled deployment/ns/app:\nghcr.io/a/b: newer version found (1.2.0), update or approval follows",
                         poll_results_to_str([PollResult("ghcr.io/a/b", True, "", "1.2.0")], "deployment/ns/app"))
        self.assertEqual("Polled deployment/ns/app:\nghcr.io/a/b: up to date",
                         poll_results_to_str([PollResult("ghcr.io/a/b", False)], "deployment/ns/app"))

    def test_all(self):
        results = [PollResult("a", True), PollResult("b", False), PollResult("c", False),
                   PollResult("d", False, "unauthorized")]
        self.assertEqual("\n".join([
            "Polled 4 images: 1 newer, 1 failed, 2 up to date",
            "a: newer version found, update or approval follows",
            "d: error: unauthorized",
        ]), poll_results_to_str(results))


class PollBotTest(TestBase):

    def setUp(self):
        self.api = Mock(spec=KeelApiClient)
        self.api.get_resources.return_value = [
            _resource("deployment/homeassistant/music-assistant", ["ghcr.io/music-assistant/server:2.4.0"]),
            _resource("deployment/media/jellyfin", ["jellyfin/jellyfin:10.10"]),
            _resource("deployment/media/jellyseerr", ["fallenbagel/jellyseerr:2.0"]),
        ]
        self.api.poll.return_value = [PollResult("ghcr.io/music-assistant/server", True, "", "2.5.0")]
        self.store = Store()
        self.bot = KeelTelegramBot(_config(), self.api, store=self.store)
        self.telegram = MagicMock()
        self.telegram.username = "keelbot"
        self.telegram.send_message = AsyncMock(side_effect=lambda **kwargs: Mock(chat_id=CHAT, message_id=50))
        self.telegram.edit_message_text = AsyncMock()
        self.telegram.answer_callback_query = AsyncMock()

    def _run(self, coroutine):
        async def run():
            await coroutine
            # the poll runs in the background
            while len(self.bot._background_tasks) > 0:
                await asyncio.gather(*self.bot._background_tasks)

        asyncio.run(run())

    def _context(self):
        context = Mock(spec=CallbackContext)
        context.bot = self.telegram
        return context

    def _command(self, text: str, username=ADMIN):
        update = Mock(spec=Update)
        update.effective_message = Mock(spec=Message)
        update.effective_message.text = text
        update.effective_message.chat_id = CHAT
        update.effective_message.message_id = 10
        update.effective_message.from_user.username = username
        update.effective_message.from_user.id = 1
        update.effective_chat.id = CHAT
        update.effective_user.id = 1
        self._run(self.bot._poll_callback(update, self._context()))
        return update

    def _sent_texts(self):
        return [x.kwargs["text"] for x in self.telegram.send_message.call_args_list]

    def _result_text(self):
        return self.telegram.edit_message_text.call_args.args[0]

    def test_poll_all(self):
        self.api.poll.return_value = [PollResult("ghcr.io/music-assistant/server", True, "", "2.5.0"),
                                      PollResult("jellyfin/jellyfin", False)]

        self._command("/poll")

        self.api.poll.assert_called_once_with(None)
        self.assertEqual(["Polling all watched images, this can take a minute..."], self._sent_texts())
        self.assertEqual(
            "Polled 2 images: 1 newer, 1 up to date\n"
            "ghcr.io/music-assistant/server: newer version found (2.5.0), update or approval follows",
            self._result_text())
        self.assertEqual(50, self.telegram.edit_message_text.call_args.kwargs["message_id"])

    def test_poll_all_respects_chat_filters(self):
        self.bot._config.TELEGRAM_FILTERS.value = [{"chat_id": str(CHAT), "identifier": "media/"}]
        self.api.poll.return_value = [PollResult("ghcr.io/music-assistant/server", True, "", "2.5.0"),
                                      PollResult("jellyfin/jellyfin", True, "", "10.11")]

        self._command("/poll")

        self.assertNotIn("music-assistant", self._result_text())
        self.assertIn("jellyfin/jellyfin: newer version found (10.11)", self._result_text())

    def test_poll_exact_identifier(self):
        self._command("/poll deployment/homeassistant/music-assistant")

        self.api.poll.assert_called_once_with("deployment/homeassistant/music-assistant")
        self.assertEqual(["Polling deployment/homeassistant/music-assistant..."], self._sent_texts())
        self.assertEqual("Polled deployment/homeassistant/music-assistant:\n"
                         "ghcr.io/music-assistant/server: newer version found (2.5.0), update or approval follows",
                         self._result_text())

    def test_poll_part_of_a_name_asks_for_a_selection(self):
        update = self._command("/poll jelly")

        self.api.poll.assert_not_called()
        keyboard = self.telegram.send_message.call_args.kwargs["reply_markup"]
        options = [b.text for row in keyboard.keyboard for b in row]
        self.assertIn("deployment/media/jellyfin", options)
        self.assertIn("deployment/media/jellyseerr", options)

        # the user picks one
        update.effective_message.text = "deployment/media/jellyseerr"
        self._run(self.bot._any_message_callback(update, self._context()))

        self.api.poll.assert_called_once_with("deployment/media/jellyseerr")

    def test_not_allowed(self):
        self._command("/poll", username="someone")
        self.api.poll.assert_not_called()

    def _poll_error_text(self, error: Exception) -> str:
        self.api.poll.side_effect = error
        self._command("/poll deployment/homeassistant/music-assistant")
        return self._result_text()

    def test_errors(self):
        self.assertEqual("deployment/homeassistant/music-assistant is not watched by Keel's poll trigger: "
                         "no poll trigger", self._poll_error_text(PollNotWatchedError("no poll trigger")))
        self.assertIn("no POST /v1/poll endpoint", self._poll_error_text(PollUnsupportedError("x")))
        self.assertEqual("Keel is polling all images already, try again in a minute.",
                         self._poll_error_text(PollBusyError("x")))
        self.assertIn("did not answer in time", self._poll_error_text(requests.ReadTimeout("x")))
        self.assertIn("failed: HTTP 500 boom",
                      self._poll_error_text(requests.HTTPError(response=_response(500, b"boom"))))

    def _click(self, data: str, username=ADMIN, text="New image is available\nExpires: 11/23 10:00:00 (23h)"):
        update = MagicMock()
        update.callback_query.data = data
        update.callback_query.id = "q1"
        update.callback_query.from_user.username = username
        update.effective_chat.id = CHAT
        update.effective_message.text = text
        update.effective_message.message_id = 7
        self._run(self.bot._inline_keyboard_click_callback(update, self._context()))
        return update

    def test_button(self):
        self._click("p:deployment/homeassistant/music-assistant")

        self.api.poll.assert_called_once_with("deployment/homeassistant/music-assistant")
        self.telegram.answer_callback_query.assert_called_once_with(
            "q1", text="Checking deployment/homeassistant/music-assistant...")
        kwargs = self.telegram.send_message.call_args.kwargs
        self.assertEqual(7, kwargs["reply_to_message_id"])
        self.assertIn("newer version found (2.5.0)", kwargs["text"])

    def test_button_not_allowed(self):
        self._click("p:deployment/homeassistant/music-assistant", username="someone")

        self.api.poll.assert_not_called()
        self.telegram.answer_callback_query.assert_called_once_with("q1", text="You are not allowed to do this")

    def test_button_respects_chat_filters(self):
        self.bot._config.TELEGRAM_FILTERS.value = [{"chat_id": str(CHAT), "identifier": "media/"}]
        self._click("p:deployment/homeassistant/music-assistant")
        self.api.poll.assert_not_called()

    def test_button_without_identifier_uses_the_approval_message(self):
        self.store.register(CHAT, 7, "a1", "deployment/homeassistant/music-assistant:2.5.0")
        self._click("p")
        self.api.poll.assert_called_once_with("deployment/homeassistant/music-assistant")

    def test_button_without_identifier_uses_the_notification_text(self):
        self._click("p", text="update resource: success\ndeployment/media/jellyfin\ndeployment update\nok")
        self.api.poll.assert_called_once_with("deployment/media/jellyfin")

    def test_button_without_identifier_unknown(self):
        self._click("p")
        self.api.poll.assert_not_called()
        self.telegram.answer_callback_query.assert_called_once_with(
            "q1", text="Cannot tell which resource this is about, use /poll")

    def test_approval_buttons(self):
        menu = self.bot.create_approval_notification_menu(_approval(identifier="deployment/ns/app:1.1.0"))
        buttons = {b.text: b.callback_data for row in menu.inline_keyboard for b in row}
        self.assertEqual({"Approve": "a:a1", "Reject": "r:a1", "Check now": "p:deployment/ns/app"}, buttons)

        menu = self.bot.create_approval_notification_menu(_approval(archived=True, votes=1))
        self.assertEqual(["Approved"], [b.text for row in menu.inline_keyboard for b in row])

    def test_notification_button(self):
        send = AsyncMock()
        with patch("keel_telegram_bot.bot.send_message", new=send), \
                patch.object(type(self.bot), "bot", new=property(lambda _: self.telegram)):
            asyncio.run(self.bot.on_notification({
                "identifier": "deployment/media/jellyfin", "name": "update resource", "type": "deployment update",
                "level": "success", "message": "Successfully updated deployment media/jellyfin (10.11)",
            }))

        menu = send.call_args.kwargs["menu"]
        self.assertEqual({"Check now": "p:deployment/media/jellyfin"},
                         {b.text: b.callback_data for row in menu.inline_keyboard for b in row})

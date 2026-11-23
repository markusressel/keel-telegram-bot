import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, AsyncMock, MagicMock, PropertyMock, patch

from kubernetes.client import V1Container, V1ContainerState, V1ContainerStateRunning, \
    V1ContainerStateWaiting, V1ContainerStatus, V1ObjectMeta, V1Pod, V1PodSpec, V1PodStatus
from telegram import Message, Update
from telegram.ext import CallbackContext

from keel_telegram_bot.bot import KeelTelegramBot
from keel_telegram_bot.client.api_client import KeelApiClient
from keel_telegram_bot.client.approval import Approval
from keel_telegram_bot.client.poll_result import PollResult
from keel_telegram_bot.client.self_pod import SelfPodClient, running_digests_of_pod
from keel_telegram_bot.client.types import Provider
from keel_telegram_bot.db import Store, DeferredApproval, DEFERRAL_SOURCE_BUTTON
from keel_telegram_bot.helm.chart import HelmChart
from keel_telegram_bot.helm.checker import HelmChartUpdateChecker
from keel_telegram_bot.helm.client import HelmChartClient, InstallJobResult, InstallJobStatus
from keel_telegram_bot.helm.state import HelmChartState
from keel_telegram_bot.util import approval_new_digest, approval_repository, parse_image_id
from tests import TestBase

CHAT = 12345678
ADMIN = "myadminuser"
SELF = "deployment/keel/keel"
KEEL_IMAGE = "ghcr.io/markusressel/keel"
OLD_DIGEST = "sha256:" + "a" * 64
NEW_DIGEST = "sha256:" + "b" * 64


def _config(self_identifier=SELF):
    config = MagicMock()
    config.TELEGRAM_BOT_TOKEN.value = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    config.TELEGRAM_CHAT_IDS.value = [str(CHAT)]
    config.TELEGRAM_ADMIN_USERNAMES.value = [ADMIN]
    config.TELEGRAM_FILTERS.value = []
    config.KEEL_SELF_IDENTIFIER.value = self_identifier
    config.HELM_CHARTS_JOB_TIMEOUT.value = timedelta(minutes=1)
    return config


def _approval(id="k1", identifier=SELF + ":latest", digest=NEW_DIGEST, repository=KEEL_IMAGE, rejected=False,
              archived=False, votes=0) -> Approval:
    now = datetime.now(timezone.utc)
    event = {"repository": {"host": "", "name": repository, "tag": "latest", "digest": digest},
             "createdAt": "0001-01-01T00:00:00Z", "triggerName": "poll"}
    return Approval(
        id=id, archived=archived, provider=Provider.Kubernetes, identifier=identifier, event=event,
        message="New image is available for resource keel/keel (latest -> latest).",
        currentVersion="latest", newVersion="latest", digest="",
        votesRequired=1, votesReceived=votes, voters=[], rejected=rejected,
        deadline=now + timedelta(hours=23), createdAt=now, updatedAt=now,
    )


def _chart(name="loki", version="20.2.0"):
    return HelmChart(name=name, namespace="kube-system", chart=name, repo="https://x", version=version,
                     target_namespace=name)


def _status(name, image_id, waiting=False):
    state = V1ContainerState(waiting=V1ContainerStateWaiting(reason="ContainerCreating")) if waiting \
        else V1ContainerState(running=V1ContainerStateRunning())
    return V1ContainerStatus(name=name, image="x", image_id=image_id, ready=True, restart_count=0, state=state)


def _pod(keel_image_id=f"{KEEL_IMAGE}@{OLD_DIGEST}", waiting=False):
    return V1Pod(
        metadata=V1ObjectMeta(name="keel-abc", namespace="keel"),
        spec=V1PodSpec(containers=[
            V1Container(name="keel", image=f"{KEEL_IMAGE}:latest"),
            V1Container(name="telegram-bot", image="ghcr.io/markusressel/keel-telegram-bot:latest"),
        ]),
        status=V1PodStatus(container_statuses=[
            _status("keel", keel_image_id, waiting),
            _status("telegram-bot", "ghcr.io/markusressel/keel-telegram-bot@sha256:" + "c" * 64),
        ]),
    )


def _buttons(markup):
    return {b.text: b.callback_data for row in markup.inline_keyboard for b in row}


class DigestTest(TestBase):

    def test_parse_image_id(self):
        self.assertEqual(OLD_DIGEST, parse_image_id(f"{KEEL_IMAGE}@{OLD_DIGEST}"))
        self.assertEqual(OLD_DIGEST, parse_image_id(f"docker-pullable://{KEEL_IMAGE}@{OLD_DIGEST}"))
        self.assertEqual(OLD_DIGEST, parse_image_id(OLD_DIGEST))
        self.assertIsNone(parse_image_id(""))
        self.assertIsNone(parse_image_id(None))
        self.assertIsNone(parse_image_id(f"{KEEL_IMAGE}:latest"))

    def test_approval_digest_and_repository(self):
        self.assertEqual(NEW_DIGEST, approval_new_digest(_approval()))
        self.assertEqual(KEEL_IMAGE, approval_repository(_approval()))
        # the digest field wins if Keel ever fills it
        approval = _approval()
        approval.digest = OLD_DIGEST
        self.assertEqual(OLD_DIGEST, approval_new_digest(approval))
        self.assertIsNone(approval_new_digest(_approval(digest="")))
        approval.event = "push"
        approval.digest = ""
        self.assertIsNone(approval_new_digest(approval))
        self.assertIsNone(approval_repository(approval))

    def test_running_digests_of_pod(self):
        self.assertEqual({OLD_DIGEST}, running_digests_of_pod(_pod(), {KEEL_IMAGE}))
        # only the containers of the repository count
        self.assertEqual(set(), running_digests_of_pod(_pod(), {"ghcr.io/other/image"}))
        # a waiting container tells nothing
        self.assertEqual(set(), running_digests_of_pod(_pod(waiting=True), {KEEL_IMAGE}))
        self.assertEqual(set(), running_digests_of_pod(_pod(keel_image_id=""), {KEEL_IMAGE}))

    def test_self_pod_client(self):
        pod_client = SelfPodClient(pod_name="keel-abc", namespace="keel")
        pod_client._core_api = Mock()
        pod_client._core_api.read_namespaced_pod.return_value = _pod()
        self.assertEqual({OLD_DIGEST}, pod_client.running_digests({KEEL_IMAGE}))
        pod_client._core_api.read_namespaced_pod.assert_called_once_with("keel-abc", "keel")

        pod_client._core_api.read_namespaced_pod.side_effect = RuntimeError("forbidden")
        self.assertIsNone(pod_client.running_digests({KEEL_IMAGE}))

        self.assertIsNone(SelfPodClient(pod_name="", namespace="keel").running_digests({KEEL_IMAGE}))


class DeferralStoreTest(TestBase):

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.url = "sqlite:///" + os.path.join(self._dir.name, "state.db")

    def tearDown(self):
        self._dir.cleanup()

    def test_survives_restart_and_is_removed_once(self):
        deferral = DeferredApproval("k1", SELF + ":latest", "Markus", "a poll", CHAT, 7, DEFERRAL_SOURCE_BUTTON)
        Store(self.url).add_deferral(deferral)

        store = Store(self.url)
        self.assertEqual([deferral], store.deferrals())
        # deferring again keeps the first one
        store.add_deferral(DeferredApproval("k1", SELF + ":latest", "Other", "x", CHAT, 8, DEFERRAL_SOURCE_BUTTON))
        self.assertEqual(deferral, store.get_deferral("k1"))

        self.assertTrue(store.remove_deferral("k1"))
        self.assertFalse(store.remove_deferral("k1"))
        self.assertEqual([], Store(self.url).deferrals())


class SelfUpdateTestBase(TestBase):

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.url = "sqlite:///" + os.path.join(self._dir.name, "state.db")
        self.api = Mock(spec=KeelApiClient)
        self.approvals = [_approval()]
        self.api.get_approvals.side_effect = lambda rejected=None, archived=None: [
            x for x in self.approvals
            if (rejected is None or x.rejected == rejected) and (archived is None or x.archived == archived)]
        self.helm = Mock(spec=HelmChartClient)
        self.helm.wait_for_install_job.return_value = InstallJobResult(InstallJobStatus.SUCCEEDED, "done", None)
        self.helm.get_helm_chart.return_value = _chart()
        self.pod = Mock(spec=SelfPodClient)
        self.pod.running_digests.return_value = {OLD_DIGEST}

        self.telegram = MagicMock()
        self.telegram.username = "keelbot"
        self.telegram.send_message = AsyncMock(side_effect=lambda **kwargs: Mock(chat_id=CHAT, message_id=50))
        self.telegram.edit_message_text = AsyncMock()
        self.telegram.edit_message_reply_markup = AsyncMock()
        self.telegram.answer_callback_query = AsyncMock()
        bot_property = patch.object(KeelTelegramBot, "bot", new_callable=PropertyMock, return_value=self.telegram)
        bot_property.start()
        self.addCleanup(bot_property.stop)
        self.bot = self._new_bot()

    def tearDown(self):
        self._dir.cleanup()

    def _new_bot(self, config=None):
        """
        A bot with the database of the test, like after a restart
        """
        self.store = Store(self.url)
        return KeelTelegramBot(config or _config(), self.api, self.helm, Mock(spec=HelmChartUpdateChecker),
                               HelmChartState(os.path.join(self._dir.name, "helm.json")), self.store, self.pod)

    def _run(self, coroutine):
        async def run():
            await coroutine
            while len(self.bot._background_tasks) > 0:
                await asyncio.gather(*list(self.bot._background_tasks))

        asyncio.run(run())

    def _context(self):
        context = Mock(spec=CallbackContext)
        context.bot = self.telegram
        return context

    def _click(self, data: str):
        update = MagicMock()
        update.callback_query.data = data
        update.callback_query.id = "q1"
        update.callback_query.from_user.username = ADMIN
        update.callback_query.from_user.full_name = "Markus"
        update.effective_chat.id = CHAT
        update.effective_message.text = "New image is available"
        update.effective_message.message_id = 7
        update.effective_message.edit_reply_markup = AsyncMock()
        self._run(self.bot._inline_keyboard_click_callback(update, self._context()))
        return update

    def _command(self, text: str):
        update = Mock(spec=Update)
        update.effective_message = Mock(spec=Message)
        update.effective_message.text = text
        update.effective_message.chat_id = CHAT
        update.effective_message.message_id = 10
        update.effective_message.from_user.username = ADMIN
        update.effective_message.from_user.id = 1
        update.effective_chat.id = CHAT
        update.effective_user.id = 1
        update.effective_user.full_name = "Markus"
        self._run(self.bot._approve_callback(update, self._context()))
        return update

    def _answer(self):
        return self.telegram.answer_callback_query.call_args.kwargs["text"]

    def _sent_texts(self):
        return [x.kwargs["text"] for x in self.telegram.send_message.call_args_list]

    def _start_helm_upgrade(self):
        self.store.add_pending_upgrade("loki", "20.3.0", CHAT, 3)

    def _finish_helm_upgrade(self, bot=None):
        bot = bot or self.bot
        self._run(bot._watch_helm_chart_upgrade(self.telegram, _chart(), "20.3.0", [(CHAT, 3)]))


class DeferralTest(SelfUpdateTestBase):

    def test_button_defers_while_a_helm_upgrade_runs(self):
        self._start_helm_upgrade()

        update = self._click("a:k1")

        self.api.approve.assert_not_called()
        self.assertEqual("Deferred until the loki 20.3.0 upgrade finishes, approving restarts Keel and this bot",
                         self._answer())
        markup = update.effective_message.edit_reply_markup.call_args.args[0]
        self.assertEqual({"Deferred until the loki 20.3.0 upgrade finishes": "_", "Approve now anyway": "af:k1",
                          "Reject": "r:k1"}, _buttons(markup))
        deferral = self.store.get_deferral("k1")
        self.assertEqual(("Markus", "the loki 20.3.0 upgrade", CHAT, 7, "button"),
                         (deferral.voter, deferral.reason, deferral.chat_id, deferral.message_id, deferral.source))

    def test_deferred_approval_is_sent_when_the_upgrade_finishes(self):
        self._start_helm_upgrade()
        self._click("a:k1")

        self._finish_helm_upgrade()

        self.api.approve.assert_called_once_with("k1", SELF + ":latest", "Markus")
        self.assertIsNone(self.store.get_deferral("k1"))
        self.assertIn("Sending the deferred approval of deployment/keel/keel:latest to Keel: "
                      "the loki 20.3.0 upgrade finished.", self._sent_texts())
        # the report is a reply to the approval notification
        report = [x for x in self.telegram.send_message.call_args_list if "deferred" in x.kwargs["text"]][0]
        self.assertEqual(7, report.kwargs["reply_to_message_id"])

    def test_failed_or_timed_out_upgrade_counts_as_done(self):
        for status in (InstallJobStatus.FAILED, InstallJobStatus.TIMEOUT):
            self.api.approve.reset_mock()
            self.helm.wait_for_install_job.return_value = InstallJobResult(status, "x", None)
            self._start_helm_upgrade()
            self._click("a:k1")
            self.api.approve.assert_not_called()

            self._finish_helm_upgrade()

            self.api.approve.assert_called_once_with("k1", SELF + ":latest", "Markus")

    def test_waits_for_all_work(self):
        self._start_helm_upgrade()
        self.bot._running_polls = 1
        self._click("a:k1")
        self.assertEqual("Deferred until the loki 20.3.0 upgrade and a poll finish, approving restarts Keel and "
                         "this bot", self._answer())

        self._finish_helm_upgrade()
        self.api.approve.assert_not_called()

        self.bot._running_polls = 0
        self._run(self.bot._on_work_finished())
        self.api.approve.assert_called_once()

    def test_poll_defers_and_finishing_poll_sends(self):
        self.bot._running_polls = 1
        self._click("a:k1")
        self.assertIn("Deferred until a poll finishes", self._answer())
        self.bot._running_polls = 0

        self.api.poll.return_value = [PollResult(KEEL_IMAGE, False)]
        self._run(self.bot._poll_and_report(self.telegram, CHAT, None, reply_to=1))

        self.assertEqual(0, self.bot._running_polls)
        self.api.approve.assert_called_once_with("k1", SELF + ":latest", "Markus")

    def test_running_poll_is_work_in_progress(self):
        seen = []
        self.api.poll.side_effect = lambda identifier: seen.append(self.bot._work_in_progress()) or []
        self._run(self.bot._poll_and_report(self.telegram, CHAT, None, reply_to=1))
        self.assertEqual([["a poll"]], seen)
        self.assertEqual([], self.bot._work_in_progress())

    def test_resumes_after_restart(self):
        self._start_helm_upgrade()
        self._click("a:k1")

        # the bot restarts while the upgrade runs: the deferral and the upgrade are in the database
        self.bot = self._new_bot()
        self._run(self.bot._resume_helm_chart_upgrades())

        self.api.approve.assert_called_once_with("k1", SELF + ":latest", "Markus")
        self.assertEqual([], self.store.deferrals())

    def test_deferred_until_a_poll_is_sent_after_restart(self):
        # a poll is not resumed: after the restart nothing runs anymore
        self.bot._running_polls = 1
        self._click("a:k1")

        self.bot = self._new_bot()
        self._run(self.bot.process_deferred_approvals())

        self.api.approve.assert_called_once_with("k1", SELF + ":latest", "Markus")

    def test_expired_rejected_or_approved_meanwhile_drops_the_deferral(self):
        cases = [
            ([], "the approval expired or was deleted"),
            ([_approval(rejected=True)], "the approval was rejected"),
            ([_approval(archived=True, votes=1)], "the approval was approved already"),
        ]
        for approvals, reason in cases:
            self.telegram.send_message.reset_mock()
            self._start_helm_upgrade()
            self.approvals = [_approval()]
            self._click("a:k1")

            self.approvals = approvals
            self._run(self.bot.update_messages())

            self.assertIsNone(self.store.get_deferral("k1"))
            self.assertIn(f"Dropped the deferred approval of deployment/keel/keel:latest: {reason}.",
                          self._sent_texts())
            self._finish_helm_upgrade()
            self.api.approve.assert_not_called()

    def test_approve_now_anyway(self):
        self._start_helm_upgrade()
        self._click("a:k1")

        self._click("af:k1")

        self.api.approve.assert_called_once_with("k1", SELF + ":latest", "Markus")
        self.assertIsNone(self.store.get_deferral("k1"))
        self.assertEqual("Approved 'deployment/keel/keel:latest'", self._answer())

        # nothing is sent a second time when the upgrade finishes
        self._finish_helm_upgrade()
        self.api.approve.assert_called_once()

    def test_not_deferred_when_idle(self):
        self._click("a:k1")
        self.api.approve.assert_called_once_with("k1", SELF + ":latest", "Markus")
        self.assertEqual([], self.store.deferrals())

    def test_other_workloads_are_not_deferred(self):
        self.approvals = [_approval(id="o1", identifier="deployment/media/jellyfin:10.11")]
        self._start_helm_upgrade()
        self._click("a:o1")
        self.api.approve.assert_called_once_with("o1", "deployment/media/jellyfin:10.11", "Markus")

    def test_disabled_without_self_identifier(self):
        self.bot = self._new_bot(_config(self_identifier=""))
        self._start_helm_upgrade()
        self._click("a:k1")
        self.api.approve.assert_called_once()

    def test_upgrades_are_ignored_without_helm_client(self):
        # rows of a Helm chart upgrade that nobody watches must not block the approval forever
        self.store = Store(self.url)
        self.bot = KeelTelegramBot(_config(), self.api, store=self.store, self_pod=self.pod)
        self._start_helm_upgrade()
        self.assertEqual([], self.bot._work_in_progress())

    def test_command_defers_and_force_approves(self):
        self._start_helm_upgrade()

        self._command("/approve k1")

        self.api.approve.assert_not_called()
        self.assertEqual(["Deferred until the loki 20.3.0 upgrade finishes: approving deployment/keel/keel:latest "
                          "restarts Keel and this bot. The approval is sent to Keel as soon as that is done, "
                          "/approve k1 --force sends it now."], self._sent_texts())
        deferral = self.store.get_deferral("k1")
        self.assertEqual(("command", 50), (deferral.source, deferral.message_id))

        self._command("/approve k1 --force")

        self.api.approve.assert_called_once_with("k1", SELF + ":latest", "Markus")
        self.assertIsNone(self.store.get_deferral("k1"))

    def test_command_deferral_message_is_edited_when_sent(self):
        self._start_helm_upgrade()
        self._command("/approve k1")

        self._finish_helm_upgrade()

        self.api.approve.assert_called_once()
        texts = [x.args[0] for x in self.telegram.edit_message_text.call_args_list]
        self.assertIn("Sending the deferred approval of deployment/keel/keel:latest to Keel: "
                      "the loki 20.3.0 upgrade finished.", texts)
        self.assertEqual(50, self.telegram.edit_message_text.call_args.kwargs["message_id"])

    def test_failed_approval_is_reported(self):
        self.api.approve.side_effect = RuntimeError("keel down")
        self._start_helm_upgrade()
        self._click("a:k1")

        self._finish_helm_upgrade()

        self.assertIn("Sending the deferred approval of deployment/keel/keel:latest to Keel failed: keel down",
                      self._sent_texts())


class StaleOfferTest(SelfUpdateTestBase):

    def test_new_approval_of_running_image_is_closed(self):
        self.pod.running_digests.return_value = {NEW_DIGEST}

        self._run(self.bot.on_new_pending_approval(_approval()))

        self.pod.running_digests.assert_called_once_with({KEEL_IMAGE})
        self.api.delete.assert_called_once_with("k1", SELF + ":latest", "keel-telegram-bot")
        menu = self.telegram.send_message.call_args.kwargs["reply_markup"]
        self.assertEqual({"Already running, closed": "_"}, _buttons(menu))
        # nothing to follow anymore
        self.assertEqual([], self.store.all())
        self.assertTrue(self.store.is_announced("k1", CHAT))

    def test_new_approval_of_other_image_is_announced(self):
        self._run(self.bot.on_new_pending_approval(_approval()))

        self.api.delete.assert_not_called()
        menu = self.telegram.send_message.call_args.kwargs["reply_markup"]
        self.assertIn("Approve", _buttons(menu))
        self.assertEqual(["k1"], [x.approval_id for x in self.store.all()])

    def test_unknown_digests_leave_the_approval_alone(self):
        cases = [
            (None, _approval()),  # running digest unknown
            ({NEW_DIGEST}, _approval(digest="")),  # offered digest unknown
        ]
        for running, approval in cases:
            self.pod.running_digests.return_value = running
            self.assertIsNone(asyncio.run(self.bot._is_offer_running(approval)))
        self.bot._self_pod = None
        self.assertIsNone(asyncio.run(self.bot._is_offer_running(_approval())))

        self.bot._self_pod = self.pod
        self.pod.running_digests.return_value = None
        self._run(self.bot.on_new_pending_approval(_approval()))
        self.api.delete.assert_not_called()

    def test_repository_from_the_resource_if_the_event_has_none(self):
        self.api.get_resource.return_value = Mock(images=[f"{KEEL_IMAGE}:latest"])
        self.pod.running_digests.return_value = {NEW_DIGEST}
        self.assertTrue(asyncio.run(self.bot._is_offer_running(_approval(repository=""))))
        self.api.get_resource.assert_called_once_with(SELF)
        self.pod.running_digests.assert_called_once_with({KEEL_IMAGE})

    def test_other_workloads_are_not_checked(self):
        self.pod.running_digests.return_value = {NEW_DIGEST}
        self._run(self.bot.on_new_pending_approval(_approval(id="o1", identifier="deployment/media/app:latest")))
        self.pod.running_digests.assert_not_called()
        self.api.delete.assert_not_called()

    def test_already_announced_is_not_checked_again(self):
        self.store.mark_announced("k1", CHAT)
        self._run(self.bot.on_new_pending_approval(_approval()))
        self.pod.running_digests.assert_not_called()

    def test_start_closes_offers_of_the_running_image(self):
        # announced before Keel was restarted by hand and pulled the same image, with a deferred approval
        self.store.register(CHAT, 7, "k1", SELF + ":latest", "0|0|0/1")
        self.store.add_deferral(DeferredApproval("k1", SELF + ":latest", "Markus", "a poll", CHAT, 7,
                                                 DEFERRAL_SOURCE_BUTTON))
        self.pod.running_digests.return_value = {NEW_DIGEST}

        self._run(self.bot._close_stale_self_approvals())

        self.api.delete.assert_called_once_with("k1", SELF + ":latest", "keel-telegram-bot")
        markup = self.telegram.edit_message_reply_markup.call_args.kwargs["reply_markup"]
        self.assertEqual({"Already running, closed": "_"}, _buttons(markup))
        self.assertEqual(7, self.telegram.edit_message_reply_markup.call_args.kwargs["message_id"])
        self.assertEqual([], self.store.all())
        self.assertEqual([], self.store.deferrals())
        self.assertIn("Dropped the deferred approval of deployment/keel/keel:latest: "
                      "Keel runs the offered image already.", self._sent_texts())
        self.api.approve.assert_not_called()

    def test_start_check_runs_until_it_worked_once(self):
        self.pod.running_digests.return_value = {NEW_DIGEST}
        self.api.get_approvals.side_effect = RuntimeError("keel not up yet")
        with self.assertRaises(RuntimeError):
            self._run(self.bot.close_stale_self_approvals_once())

        self.api.get_approvals.side_effect = lambda rejected=None, archived=None: self.approvals
        self._run(self.bot.close_stale_self_approvals_once())
        self._run(self.bot.close_stale_self_approvals_once())

        self.api.delete.assert_called_once()

    def test_start_leaves_other_offers_alone(self):
        self.store.register(CHAT, 7, "k1", SELF + ":latest", "0|0|0/1")

        self._run(self.bot._close_stale_self_approvals())

        self.api.delete.assert_not_called()
        self.assertEqual(["k1"], [x.approval_id for x in self.store.all()])

    def test_failed_delete_keeps_the_approval(self):
        self.pod.running_digests.return_value = {NEW_DIGEST}
        self.api.delete.side_effect = RuntimeError("keel down")

        self._run(self.bot.on_new_pending_approval(_approval()))

        menu = self.telegram.send_message.call_args.kwargs["reply_markup"]
        self.assertIn("Approve", _buttons(menu))
        self.assertEqual(["k1"], [x.approval_id for x in self.store.all()])

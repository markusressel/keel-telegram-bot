import asyncio
import unittest
from datetime import timedelta
from unittest.mock import Mock, AsyncMock

from keel_telegram_bot.bot import KeelTelegramBot
from keel_telegram_bot.client.api_client import KeelApiClient
from keel_telegram_bot.db import Store
from keel_telegram_bot.monitoring import RegularIntervalWorker
from keel_telegram_bot.monitoring.monitor import Monitor


async def wait_for(condition, timeout: float = 5):
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


class _Worker(RegularIntervalWorker):

    def __init__(self, fail_first: bool = False):
        super().__init__(interval=0.01)
        self.runs = 0
        self.loops = []
        self.fail_first = fail_first
        self.background_done = None

    async def _run(self):
        self.runs += 1
        self.loops.append(asyncio.get_running_loop())
        if self.fail_first and self.runs == 1:
            raise RuntimeError("first run fails")
        if self.background_done is None:
            # like the watcher of an automatic Helm chart upgrade: outlives the run that started it
            self.background_done = asyncio.Event()
            asyncio.create_task(self._background(self.background_done))

    @staticmethod
    async def _background(done: asyncio.Event):
        await asyncio.sleep(0.05)
        done.set()


class WorkerTest(unittest.TestCase):

    def test_runs_on_the_loop_of_start_and_keeps_background_tasks(self):
        async def run():
            worker = _Worker()
            task = asyncio.create_task(worker.start())
            await wait_for(lambda: worker.runs >= 3)
            await asyncio.wait_for(worker.background_done.wait(), timeout=5)
            worker.stop()
            await asyncio.wait_for(task, timeout=5)
            self.assertTrue(all(x is asyncio.get_running_loop() for x in worker.loops))

        asyncio.run(run())

    def test_failing_run_does_not_stop_the_worker(self):
        async def run():
            worker = _Worker(fail_first=True)
            task = asyncio.create_task(worker.start())
            await wait_for(lambda: worker.runs >= 2)
            worker.stop()
            await asyncio.wait_for(task, timeout=5)

        asyncio.run(run())

    def test_start_twice(self):
        async def run():
            worker = _Worker()
            task = asyncio.create_task(worker.start())
            await wait_for(lambda: worker.runs >= 1)
            self.assertIsNone(await worker.start())
            worker.stop()
            await asyncio.wait_for(task, timeout=5)

        asyncio.run(run())


class MonitorTest(unittest.TestCase):

    def test_run_fetches_approvals_and_updates_messages(self):
        config = Mock()
        config.MONITOR_INTERVAL.value = timedelta(seconds=60)
        config.TELEGRAM_CHAT_IDS.value = ["1"]
        api_client = Mock(spec=KeelApiClient)
        api_client.get_approvals.return_value = []
        bot = Mock(spec=KeelTelegramBot)
        bot.close_stale_self_approvals_once = AsyncMock()
        bot.update_messages = AsyncMock()
        monitor = Monitor(config, api_client, bot, Store())

        asyncio.run(monitor._run())

        api_client.get_approvals.assert_called_once_with(rejected=False, archived=False)
        bot.update_messages.assert_awaited_once()

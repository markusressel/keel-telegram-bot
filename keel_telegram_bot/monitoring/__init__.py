import asyncio
import logging
from typing import Optional

LOGGER = logging.getLogger(__name__)


class RegularIntervalWorker:
    """
    Base class for a worker that executes a specific task in a regular interval.

    The task runs on the event loop that awaits start(), which is the loop of the bot. Tasks that a run starts in the
    background (f.ex. the watcher of an automatic Helm chart upgrade) keep running on that loop after the run is done.
    Blocking calls in _run() belong in asyncio.to_thread().
    """

    def __init__(self, interval: float):
        self._interval = interval
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """
        Starts the worker and runs it until it is stopped
        """
        if self._task is not None:
            LOGGER.debug("Already running, ignoring start() call")
            return None

        LOGGER.debug(f"Starting worker: {self.__class__.__name__}")
        self._task = asyncio.current_task()
        try:
            while True:
                await self._run_once()
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            LOGGER.debug(f"Stopped worker: {self.__class__.__name__}")
        finally:
            self._task = None

    def stop(self):
        """
        Stops the worker
        """
        if self._task is not None:
            self._task.cancel()

    async def _run_once(self):
        """
        Runs the task once, a failing run does not stop the worker
        """
        try:
            await self._run()
        except Exception as e:
            LOGGER.error(e, exc_info=True)

    async def _run(self):
        """
        The regularly executed task. Override this method.
        """
        raise NotImplementedError()

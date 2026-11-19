import json
import logging
import os
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import List, Optional

LOGGER = logging.getLogger(__name__)

KEY_MESSAGES = "messages"

# Telegram stops accepting edits of old messages, and Keel deletes approvals after their deadline (24h by
# default). Entries older than this are forgotten, so the file cannot grow forever.
DEFAULT_MAX_AGE = timedelta(days=7)


@dataclass
class ApprovalMessage:
    """
    A Telegram message that was sent for an approval, and whose buttons have to follow the state of the approval
    """
    chat_id: int
    message_id: int
    approval_id: str
    identifier: str
    # what the message currently shows, see approval_signature(). Empty for messages of unknown content.
    signature: str = ""
    created_at: str = ""
    # consecutive failed edits that were not clearly permanent
    failures: int = 0


class ApprovalMessageState:
    """
    Remembers the Telegram messages of approval notifications, persisted as a small JSON file:

    {"messages": [{"chat_id": 1, "message_id": 2, "approval_id": "...", "identifier": "...", ...}]}

    Without it, every restart of the bot (which also happens when Keel itself is updated) makes the buttons of
    all open notifications stale: they keep showing "Approve" and "Reject" although the approval was long
    decided or has expired.
    """

    def __init__(self, path: Optional[str] = None, max_age: timedelta = DEFAULT_MAX_AGE):
        """
        :param path: file to keep the state in, None to keep it in memory only
        :param max_age: age after which a message is forgotten
        """
        self._path = path
        self._max_age = max_age
        self._lock = threading.RLock()
        self._messages: List[ApprovalMessage] = self._load()

    def register(self, chat_id: int, message_id: int, approval_id: str, identifier: str, signature: str = ""):
        """
        Remembers a message. A message that is already known only gets its signature updated.
        """
        with self._lock:
            existing = self.find(chat_id, message_id)
            if existing is not None:
                existing.signature = signature
                existing.failures = 0
            else:
                self._messages.append(ApprovalMessage(
                    chat_id=chat_id,
                    message_id=message_id,
                    approval_id=approval_id,
                    identifier=identifier,
                    signature=signature,
                    created_at=_now().isoformat(),
                ))
            self._save()

    def find(self, chat_id: int, message_id: int) -> Optional[ApprovalMessage]:
        with self._lock:
            for message in self._messages:
                if message.chat_id == chat_id and message.message_id == message_id:
                    return message
            return None

    def all(self) -> List[ApprovalMessage]:
        """
        :return: a copy of all remembered messages
        """
        with self._lock:
            return [ApprovalMessage(**asdict(x)) for x in self._messages]

    def update(self, message: ApprovalMessage, signature: Optional[str] = None, failures: Optional[int] = None):
        """
        Stores the new signature and failure count of a message
        """
        with self._lock:
            current = self.find(message.chat_id, message.message_id)
            if current is None:
                return
            if signature is not None:
                current.signature = signature
            if failures is not None:
                current.failures = failures
            self._save()

    def remove(self, message: ApprovalMessage):
        with self._lock:
            self._messages = [x for x in self._messages
                              if not (x.chat_id == message.chat_id and x.message_id == message.message_id)]
            self._save()

    def prune(self, now: Optional[datetime] = None) -> int:
        """
        Forgets messages that are older than the maximum age
        :return: the number of forgotten messages
        """
        now = now or _now()
        with self._lock:
            keep = [x for x in self._messages if not self._is_too_old(x, now)]
            removed = len(self._messages) - len(keep)
            if removed > 0:
                self._messages = keep
                self._save()
            return removed

    def _is_too_old(self, message: ApprovalMessage, now: datetime) -> bool:
        try:
            created = datetime.fromisoformat(message.created_at)
        except ValueError:
            return False
        return now - created > self._max_age

    def _load(self) -> List[ApprovalMessage]:
        if self._path is None or not os.path.exists(self._path):
            return []
        try:
            with open(self._path, "r") as file:
                data = json.load(file)
            if not isinstance(data, dict) or not isinstance(data.get(KEY_MESSAGES), list):
                raise ValueError("unexpected content")
            messages = [ApprovalMessage(**item) for item in data[KEY_MESSAGES]]
            for message in messages:
                if not message.created_at:
                    # unknown age, count it from now on instead of keeping it forever
                    message.created_at = _now().isoformat()
            return messages
        except Exception as ex:
            LOGGER.error(f"Cannot read approval message state file '{self._path}', starting with an empty state: {ex}")
            return []

    def _save(self):
        if self._path is None:
            return
        try:
            directory = os.path.dirname(os.path.abspath(self._path))
            os.makedirs(directory, exist_ok=True)
            # write to a temporary file first, so a crash never leaves a half written state file behind
            tmp_path = f"{self._path}.tmp"
            with open(tmp_path, "w") as file:
                json.dump({KEY_MESSAGES: [asdict(x) for x in self._messages]}, file, indent=2, sort_keys=True)
            os.replace(tmp_path, self._path)
        except Exception as ex:
            LOGGER.error(f"Cannot write approval message state file '{self._path}': {ex}")


def _now() -> datetime:
    return datetime.now(timezone.utc)

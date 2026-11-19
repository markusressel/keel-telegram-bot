import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from keel_telegram_bot.db.tables import approval_messages, announced_approvals, helm_pending_upgrades, meta

LOGGER = logging.getLogger(__name__)

# Telegram stops accepting edits of old messages, and Keel deletes an approval after its deadline (24h by
# default). Messages older than this are forgotten, so the table cannot grow forever.
DEFAULT_MAX_AGE = timedelta(days=7)

KEY_ANNOUNCED_SEEDED = "announced_seeded"


@dataclass
class ApprovalMessage:
    """
    A Telegram message that was sent for an approval, and whose buttons have to follow the state of the approval
    """
    chat_id: int
    message_id: int
    approval_id: str
    identifier: str
    signature: str = ""
    failures: int = 0


@dataclass
class PendingHelmUpgrade:
    name: str
    version: str
    chat_id: int
    message_id: int


def _now() -> datetime:
    # naive UTC, because SQLite cannot store time zones
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_url(url: str) -> str:
    """
    SQLAlchemy picks the psycopg2 driver for "postgresql://", this bot ships psycopg (3)
    """
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def create_engine(url: str) -> Engine:
    url = normalize_url(url)
    if url in ("sqlite://", "sqlite:///:memory:"):
        # every connection of an in-memory database is a database of its own, so share one
        return sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    if url.startswith("sqlite:///"):
        path = url[len("sqlite:///"):]
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
    return sa.create_engine(url, pool_pre_ping=True)


class Store:
    """
    The persistent state of the bot: SQLite (a file, default) or PostgreSQL, chosen by the database URL.

    Without it, every restart of the bot (which also happens when Keel itself is updated) makes the buttons of
    all open notifications stale, and an approval that appears while the bot is down is never announced.
    """

    def __init__(self, url: str = "sqlite://", max_age: timedelta = DEFAULT_MAX_AGE):
        """
        :param url: SQLAlchemy database URL, "sqlite://" keeps everything in memory only
        :param max_age: age after which an approval message is forgotten
        """
        self._max_age = max_age
        self._lock = threading.RLock()
        self._engine = create_engine(url)
        self._migrate()

    def _migrate(self):
        config = AlembicConfig()
        config.set_main_option("script_location", "keel_telegram_bot:db/migrations")
        with self._engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    # approval messages

    def register(self, chat_id: int, message_id: int, approval_id: str, identifier: str, signature: str = ""):
        """
        Remembers a message. A message that is already known only gets its signature updated.
        """
        with self._lock, self._engine.begin() as conn:
            result = conn.execute(
                sa.update(approval_messages)
                .where(approval_messages.c.chat_id == chat_id, approval_messages.c.message_id == message_id)
                .values(signature=signature, failures=0))
            if result.rowcount == 0:
                conn.execute(sa.insert(approval_messages).values(
                    chat_id=chat_id, message_id=message_id, approval_id=approval_id,
                    identifier=identifier, signature=signature, failures=0, created_at=_now()))

    def find(self, chat_id: int, message_id: int) -> Optional[ApprovalMessage]:
        with self._engine.connect() as conn:
            row = conn.execute(sa.select(approval_messages).where(
                approval_messages.c.chat_id == chat_id, approval_messages.c.message_id == message_id)).first()
        return self._to_message(row) if row else None

    def all(self) -> List[ApprovalMessage]:
        with self._engine.connect() as conn:
            rows = conn.execute(sa.select(approval_messages).order_by(approval_messages.c.created_at)).all()
        return [self._to_message(x) for x in rows]

    def update(self, message: ApprovalMessage, signature: Optional[str] = None, failures: Optional[int] = None):
        """
        Stores the new signature and failure count of a message
        """
        values = {}
        if signature is not None:
            values["signature"] = signature
        if failures is not None:
            values["failures"] = failures
        if not values:
            return
        with self._lock, self._engine.begin() as conn:
            conn.execute(sa.update(approval_messages).where(
                approval_messages.c.chat_id == message.chat_id,
                approval_messages.c.message_id == message.message_id).values(**values))

    def remove(self, message: ApprovalMessage):
        with self._lock, self._engine.begin() as conn:
            conn.execute(sa.delete(approval_messages).where(
                approval_messages.c.chat_id == message.chat_id,
                approval_messages.c.message_id == message.message_id))

    def prune(self, now: Optional[datetime] = None) -> int:
        """
        Forgets messages that are older than the maximum age
        :return: the number of forgotten messages
        """
        now = now or _now()
        with self._lock, self._engine.begin() as conn:
            result = conn.execute(sa.delete(approval_messages).where(
                approval_messages.c.created_at < now - self._max_age))
        return result.rowcount

    @staticmethod
    def _to_message(row) -> ApprovalMessage:
        return ApprovalMessage(chat_id=row.chat_id, message_id=row.message_id, approval_id=row.approval_id,
                               identifier=row.identifier, signature=row.signature, failures=row.failures)

    # announced approvals

    def is_announced(self, approval_id: str, chat_id: int) -> bool:
        with self._engine.connect() as conn:
            return conn.execute(sa.select(announced_approvals.c.approval_id).where(
                announced_approvals.c.approval_id == approval_id,
                announced_approvals.c.chat_id == chat_id)).first() is not None

    def mark_announced(self, approval_id: str, chat_id: int):
        with self._lock, self._engine.begin() as conn:
            known = conn.execute(sa.select(announced_approvals.c.approval_id).where(
                announced_approvals.c.approval_id == approval_id,
                announced_approvals.c.chat_id == chat_id)).first()
            if known is None:
                conn.execute(sa.insert(announced_approvals).values(
                    approval_id=approval_id, chat_id=chat_id, announced_at=_now()))

    def seed_announced(self, approval_ids: Iterable[str], chat_ids: Iterable[int]) -> bool:
        """
        Marks the given approvals as announced, once per database. Used on the first start with a new database:
        the approvals that are pending then were announced by an earlier version of the bot, announcing them
        again would flood the chats.
        :return: True if the seeding was done now, False if the database was seeded before
        """
        with self._lock, self._engine.begin() as conn:
            if conn.execute(sa.select(meta.c.value).where(meta.c.key == KEY_ANNOUNCED_SEEDED)).first():
                return False
            now = _now()
            rows = [{"approval_id": a, "chat_id": c, "announced_at": now}
                    for a in approval_ids for c in chat_ids]
            if rows:
                conn.execute(sa.insert(announced_approvals), rows)
            conn.execute(sa.insert(meta).values(key=KEY_ANNOUNCED_SEEDED, value=now.isoformat()))
        return True

    def forget_announced_except(self, active_approval_ids: Iterable[str]):
        """
        Forgets the announcements of approvals that are not pending anymore
        """
        active = list(active_approval_ids)
        statement = sa.delete(announced_approvals)
        if active:
            statement = statement.where(announced_approvals.c.approval_id.notin_(active))
        with self._lock, self._engine.begin() as conn:
            conn.execute(statement)

    # helm chart upgrades

    def add_pending_upgrade(self, name: str, version: str, chat_id: int, message_id: int):
        self.remove_pending_upgrade(chat_id, message_id)
        with self._lock, self._engine.begin() as conn:
            conn.execute(sa.insert(helm_pending_upgrades).values(
                chat_id=chat_id, message_id=message_id, name=name, version=version, created_at=_now()))

    def remove_pending_upgrade(self, chat_id: int, message_id: int):
        with self._lock, self._engine.begin() as conn:
            conn.execute(sa.delete(helm_pending_upgrades).where(
                helm_pending_upgrades.c.chat_id == chat_id, helm_pending_upgrades.c.message_id == message_id))

    def pending_upgrades(self) -> List[PendingHelmUpgrade]:
        with self._engine.connect() as conn:
            rows = conn.execute(sa.select(helm_pending_upgrades)).all()
        return [PendingHelmUpgrade(r.name, r.version, r.chat_id, r.message_id) for r in rows]

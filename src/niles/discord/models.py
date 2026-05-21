"""Data models."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from typing import Literal
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """A 15-minute time window."""

    start: datetime
    end: datetime


def _new_id() -> str:
    return uuid4().hex


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _default_window() -> TimeWindow:
    now = datetime.now(UTC)
    return TimeWindow(start=now, end=now)


@dataclass(frozen=True, slots=True)
class FreeTimeEntry:
    """A user's free time entry."""

    id: str = field(default_factory=_new_id)
    user_id: int = 0
    windows: tuple[TimeWindow, ...] = ()
    created_at: datetime = field(default_factory=_utc_now)
    is_removed: bool = False
    removed_reason: str | None = None


@dataclass(frozen=True, slots=True)
class EventData:
    """An event."""

    id: str = field(default_factory=_new_id)
    name: str = ""
    creator_id: int = 0
    guild_id: int = 0
    window: TimeWindow = field(default_factory=_default_window)
    participant_ids: tuple[int, ...] = ()
    moderator_ids: tuple[int, ...] = ()
    participant_thread_id: int | None = None
    moderator_thread_id: int | None = None
    is_closed: bool = False
    created_at: datetime = field(default_factory=_utc_now)


_ModVote = Literal["yes", "no", "pending"]


@dataclass(frozen=True, slots=True)
class PendingConfirmation:
    """Pending moderator confirmation state."""

    event_id: str
    reason: str | None
    action: Literal["add_user", "remove_user", "close"]
    target_user_id: int | None
    votes: dict[int, _ModVote]
    timeout_at: datetime | None
    message_id: int | None = None
    channel_id: int | None = None

"""Data models."""

from collections.abc import Sequence  # noqa: TC003
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


@dataclass(slots=True)
class _PendingConfirmation:
    """Pending moderator confirmation state."""

    event_id: str
    reason: str | None
    action: Literal["add_user", "remove_user", "close"]
    target_user_id: int | None
    votes: dict[int, _ModVote]
    timeout_at: datetime | None
    message_id: int | None = None
    channel_id: int | None = None


_PendingConfirmationRegistry: dict[str, _PendingConfirmation] = {}
"""Registry of all pending confirmations by event_id + action key."""


def _pending_key(event_id: str, action: str) -> str:
    return f"{event_id}:{action}"


def register_pending(  # noqa: PLR0913
    event_id: str,
    action: Literal["add_user", "remove_user", "close"],
    reason: str | None,
    target_user_id: int | None,
    moderator_ids: Sequence[int],
    timeout_at: datetime | None,
) -> None:
    """Register a pending confirmation."""
    key = _pending_key(event_id, action)
    _PendingConfirmationRegistry[key] = _PendingConfirmation(
        event_id=event_id,
        action=action,
        reason=reason,
        target_user_id=target_user_id,
        votes=dict.fromkeys(moderator_ids, "pending"),
        timeout_at=timeout_at,
    )


def get_pending(
    event_id: str, action: Literal["add_user", "remove_user", "close"]
) -> _PendingConfirmation | None:
    """Get a pending confirmation."""
    return _PendingConfirmationRegistry.get(_pending_key(event_id, action))


def remove_pending(
    event_id: str, action: Literal["add_user", "remove_user", "close"]
) -> None:
    """Remove a pending confirmation."""
    _PendingConfirmationRegistry.pop(_pending_key(event_id, action), None)

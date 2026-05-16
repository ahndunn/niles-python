"""Data stores."""

from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING
from typing import Literal
from typing import final

from niles.discord.models import EventData
from niles.discord.models import FreeTimeEntry
from niles.discord.models import PendingConfirmation
from niles.discord.models import TimeWindow
from niles.utils.loggers import LOGGER

if TYPE_CHECKING:
    import discord


@final
class ScheduleStore:
    """In-memory store for free time entries."""

    def __init__(self) -> None:
        """Init."""
        self._entries: dict[str, FreeTimeEntry] = {}
        self._user_entries: dict[int, list[str]] = {}

    def add_entry(
        self, user_id: int, windows: tuple[TimeWindow, ...]
    ) -> FreeTimeEntry:
        """Add a new free time entry."""
        entry = FreeTimeEntry(
            user_id=user_id, windows=windows, created_at=datetime.now(UTC)
        )
        self._entries[entry.id] = entry
        self._user_entries.setdefault(user_id, []).append(entry.id)
        LOGGER.debug(
            "Added free time entry {} for user {} ({} windows)",
            entry.id,
            user_id,
            len(windows),
        )
        return entry

    def get_user_entries(
        self, user_id: int, *, include_removed: bool = False
    ) -> list[FreeTimeEntry]:
        """Get all entries for a user."""
        ids = self._user_entries.get(user_id, [])
        result = [self._entries[eid] for eid in ids if eid in self._entries]
        if not include_removed:
            result = [e for e in result if not e.is_removed]
        return result

    def get_entry(self, entry_id: str) -> FreeTimeEntry | None:
        """Get a specific entry by ID."""
        return self._entries.get(entry_id)

    def remove_entry(
        self, entry_id: str, reason: str | None = None
    ) -> FreeTimeEntry | None:
        """Mark an entry as removed."""
        entry = self._entries.get(entry_id)
        if entry is None:
            LOGGER.warning("Remove failed: entry {} not found", entry_id)
            return None
        new_entry = FreeTimeEntry(
            id=entry.id,
            user_id=entry.user_id,
            windows=entry.windows,
            created_at=entry.created_at,
            is_removed=True,
            removed_reason=reason,
        )
        self._entries[entry_id] = new_entry
        LOGGER.debug(
            "Removed entry {} for user {} (reason={})",
            entry_id,
            entry.user_id,
            reason,
        )
        return new_entry

    def clear_user_entries(
        self,
        user_id: int,
        from_date: datetime | None = None,
        reason: str | None = None,
    ) -> list[FreeTimeEntry]:
        """Clear all non-removed entries for a user from a given date."""
        removed: list[FreeTimeEntry] = []
        ids = list(self._user_entries.get(user_id, []))
        for eid in ids:
            entry = self._entries.get(eid)
            if entry is None or entry.is_removed:
                continue
            if from_date is not None:
                has_future = any(w.start >= from_date for w in entry.windows)
                if not has_future:
                    continue
            removed_entry = self.remove_entry(eid, reason)
            if removed_entry is not None:
                removed.append(removed_entry)
        LOGGER.debug(
            "Cleared {} entries for user {} (reason={})",
            len(removed),
            user_id,
            reason,
        )
        return removed

    def get_all_entries(self) -> list[FreeTimeEntry]:
        """Get all non-removed entries."""
        return [e for e in self._entries.values() if not e.is_removed]

    def get_removed_entries(self) -> list[FreeTimeEntry]:
        """Get all removed entries with reasons."""
        return [e for e in self._entries.values() if e.is_removed]

    def get_entries_by_window(self, window: TimeWindow) -> list[FreeTimeEntry]:
        """Get all entries whose windows overlap with the given window."""
        result: list[FreeTimeEntry] = []
        for entry in self.get_all_entries():
            for ew in entry.windows:
                if ew.start < window.end and ew.end > window.start:
                    result.append(entry)
                    break
        return result

    def get_free_user_ids(self, window: TimeWindow) -> set[int]:
        """Get all user IDs free in a given time window."""
        user_ids: set[int] = set()
        for entry in self.get_all_entries():
            for ew in entry.windows:
                if ew.start < window.end and ew.end > window.start:
                    user_ids.add(entry.user_id)
                    break
        return user_ids


@final
class EventStore:
    """In-memory store for events."""

    def __init__(self) -> None:
        """Init."""
        self._events: dict[str, EventData] = {}

    def create_event(self, event: EventData) -> EventData:
        """Create a new event."""
        self._events[event.id] = event
        LOGGER.info(
            "Event created: {} (id={}, creator={})",
            event.name,
            event.id,
            event.creator_id,
        )
        return event

    def get_event(self, event_id: str) -> EventData | None:
        """Get an event by ID."""
        event = self._events.get(event_id)
        if event is None:
            LOGGER.debug("Event {} not found in store", event_id)
            return None
        return event

    def update_event(self, event: EventData) -> EventData:
        """Update an event (replace by ID)."""
        self._events[event.id] = event
        LOGGER.debug("Event {} updated (closed={})", event.id, event.is_closed)
        return event

    def get_all_events(self) -> list[EventData]:
        """Get all events."""
        return list(self._events.values())


def get_schedule_store(
    interaction: discord.Interaction,
) -> ScheduleStore | None:
    """Get the ScheduleStore from the client."""
    client = interaction.client
    store = getattr(client, "schedules", None)
    if isinstance(store, ScheduleStore):
        return store
    return None


@final
class TimezoneStore:
    """In-memory store: user_id → offset string (e.g. ``'UTC+5'``)."""

    def __init__(self) -> None:
        """Init."""
        self._timezones: dict[int, str] = {}

    def get(self, user_id: int) -> str | None:
        """Get a user's offset string, or ``None`` if not set."""
        return self._timezones.get(user_id)

    def set(self, user_id: int, offset_str: str) -> None:
        """Set a user's offset string."""
        self._timezones[user_id] = offset_str

    def has(self, user_id: int) -> bool:
        """Check if a user has a timezone set."""
        return user_id in self._timezones


@final
class PendingConfirmationStore:
    """In-memory store for pending confirmations."""

    def __init__(self) -> None:
        """Init."""
        self._entries: dict[str, PendingConfirmation] = {}

    def register(  # noqa: PLR0913 — needs all fields to build PendingConfirmation
        self,
        event_id: str,
        action: Literal["add_user", "remove_user", "close"],
        reason: str | None,
        target_user_id: int | None,
        moderator_ids: list[int],
        timeout_at: datetime | None,
    ) -> None:
        """Register a pending confirmation."""
        key = f"{event_id}:{action}"
        self._entries[key] = PendingConfirmation(
            event_id=event_id,
            action=action,
            reason=reason,
            target_user_id=target_user_id,
            votes=dict.fromkeys(moderator_ids, "pending"),
            timeout_at=timeout_at,
        )
        LOGGER.debug(
            "Pending {} for event {} registered (target={}, moderators={})",
            action,
            event_id,
            target_user_id,
            moderator_ids,
        )

    def get(
        self, event_id: str, action: Literal["add_user", "remove_user", "close"]
    ) -> PendingConfirmation | None:
        """Get a pending confirmation."""
        return self._entries.get(f"{event_id}:{action}")

    def remove(
        self, event_id: str, action: Literal["add_user", "remove_user", "close"]
    ) -> None:
        """Remove a pending confirmation."""
        self._entries.pop(f"{event_id}:{action}", None)
        LOGGER.debug("Pending {} for event {} removed", action, event_id)


def get_timezone_store(
    interaction: discord.Interaction,
) -> TimezoneStore | None:
    """Get the TimezoneStore from the client."""
    client = interaction.client
    store = getattr(client, "timezones", None)
    if isinstance(store, TimezoneStore):
        return store
    return None


def get_event_store(interaction: discord.Interaction) -> EventStore | None:
    """Get the EventStore from the client."""
    client = interaction.client
    store = getattr(client, "events", None)
    if isinstance(store, EventStore):
        return store
    return None


def get_pending_confirmation_store(
    interaction: discord.Interaction,
) -> PendingConfirmationStore | None:
    """Get the PendingConfirmationStore from the client."""
    client = interaction.client
    store = getattr(client, "pending_confirmations", None)
    if isinstance(store, PendingConfirmationStore):
        return store
    return None

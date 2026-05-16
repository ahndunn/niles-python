"""Data stores."""

from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING
from typing import final

from niles.discord.models import EventData
from niles.discord.models import FreeTimeEntry
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


def get_event_store(interaction: discord.Interaction) -> EventStore | None:
    """Get the EventStore from the client."""
    client = interaction.client
    store = getattr(client, "events", None)
    if isinstance(store, EventStore):
        return store
    return None

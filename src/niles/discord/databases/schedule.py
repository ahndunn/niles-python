"""Free-time entry schedule database."""

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from typing import final

from niles.discord.databases import Deletable
from niles.discord.databases import Readable
from niles.discord.databases import Updatable
from niles.discord.databases import Writable
from niles.discord.models import FreeTimeEntry
from niles.discord.models import TimeWindow
from niles.utils.loggers import LOGGER


@dataclass(frozen=True, slots=True)
class ByEntryId:
    """Query a single entry by its ID."""

    id: str


@dataclass(frozen=True, slots=True)
class ByUserId:
    """Query entries by user ID."""

    user_id: int


@dataclass(frozen=True, slots=True)
class ByWindow:
    """Query entries overlapping a time window."""

    window: TimeWindow


@dataclass(frozen=True, slots=True)
class AllNonRemoved:
    """Query all non-removed entries."""


@dataclass(frozen=True, slots=True)
class AllRemoved:
    """Query all removed entries."""


type _ScheduleReadQuery = (
    ByEntryId | ByUserId | ByWindow | AllNonRemoved | AllRemoved
)
type _ScheduleReadResult = FreeTimeEntry | list[FreeTimeEntry] | set[int] | None
type _ScheduleDeleteQuery = ByEntryId | ByUserId


@final
class ScheduleStore(
    Readable[_ScheduleReadQuery, _ScheduleReadResult],
    Writable[FreeTimeEntry, FreeTimeEntry],
    Deletable[_ScheduleDeleteQuery, FreeTimeEntry | list[FreeTimeEntry] | None],
    Updatable[ByEntryId, FreeTimeEntry, FreeTimeEntry],
):
    """In-memory store for free time entries."""

    def __init__(self) -> None:
        """Init."""
        self._entries: dict[str, FreeTimeEntry] = {}
        self._user_entries: dict[int, list[str]] = {}

    # ── Protocol implementations ──────────────────────────────────────

    def write(self, value: FreeTimeEntry) -> FreeTimeEntry:
        """Store an entry and index by user."""
        self._entries[value.id] = value
        self._user_entries.setdefault(value.user_id, []).append(value.id)
        return value

    def read(self, query: _ScheduleReadQuery) -> _ScheduleReadResult:
        """Read entries by query type."""
        match query:
            case ByEntryId(eid):
                return self._entries.get(eid)
            case ByUserId(uid):
                ids = self._user_entries.get(uid, [])
                return [
                    self._entries[eid] for eid in ids if eid in self._entries
                ]
            case ByWindow(window):
                result: list[FreeTimeEntry] = []
                for entry in self.get_all_entries():
                    for ew in entry.windows:
                        if ew.start < window.end and ew.end > window.start:
                            result.append(entry)
                            break
                return result
            case AllNonRemoved():
                return [e for e in self._entries.values() if not e.is_removed]
            case AllRemoved():
                return [e for e in self._entries.values() if e.is_removed]
            case _:
                return None

    def update(self, query: ByEntryId, value: FreeTimeEntry) -> FreeTimeEntry:
        """Replace an entry by ID."""
        self._entries[query.id] = value
        return value

    def delete(
        self, query: _ScheduleDeleteQuery
    ) -> FreeTimeEntry | list[FreeTimeEntry] | None:
        """Remove entries by query type."""
        match query:
            case ByEntryId(eid):
                entry = self._entries.pop(eid, None)
                if entry is not None:
                    user_ids = self._user_entries.get(entry.user_id)
                    if user_ids is not None and eid in user_ids:
                        user_ids.remove(eid)
                return entry
            case ByUserId(uid):
                removed: list[FreeTimeEntry] = []
                ids = list(self._user_entries.get(uid, []))
                for eid in ids:
                    entry = self._entries.pop(eid, None)
                    if entry is not None:
                        removed.append(entry)
                self._user_entries.pop(uid, None)
                return removed
            case _:
                return None

    # ── Domain methods ────────────────────────────────────────────────

    def add_entry(
        self, user_id: int, windows: tuple[TimeWindow, ...]
    ) -> FreeTimeEntry:
        """Add a new free time entry."""
        entry = FreeTimeEntry(
            user_id=user_id, windows=windows, created_at=datetime.now(UTC)
        )
        self.write(entry)
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
        result = self.read(ByUserId(user_id))
        if not isinstance(result, list):
            return []
        if not include_removed:
            result = [e for e in result if not e.is_removed]
        return result

    def get_entry(self, entry_id: str) -> FreeTimeEntry | None:
        """Get a specific entry by ID."""
        result = self.read(ByEntryId(entry_id))
        if isinstance(result, FreeTimeEntry):
            return result
        return None

    def remove_entry(
        self, entry_id: str, reason: str | None = None
    ) -> FreeTimeEntry | None:
        """Mark an entry as removed (soft-delete via update)."""
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
        self.update(ByEntryId(entry_id), new_entry)
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
        result = self.read(AllNonRemoved())
        return result if isinstance(result, list) else []

    def get_removed_entries(self) -> list[FreeTimeEntry]:
        """Get all removed entries with reasons."""
        result = self.read(AllRemoved())
        return result if isinstance(result, list) else []

    def get_entries_by_window(self, window: TimeWindow) -> list[FreeTimeEntry]:
        """Get all entries whose windows overlap with the given window."""
        result = self.read(ByWindow(window))
        return result if isinstance(result, list) else []

    def get_free_user_ids(self, window: TimeWindow) -> set[int]:
        """Get all user IDs free in a given time window."""
        user_ids: set[int] = set()
        for entry in self.get_all_entries():
            for ew in entry.windows:
                if ew.start < window.end and ew.end > window.start:
                    user_ids.add(entry.user_id)
                    break
        return user_ids

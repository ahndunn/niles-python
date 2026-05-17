"""Timezone database."""

from dataclasses import dataclass
from typing import final

from niles.discord.databases import Readable
from niles.discord.databases import Writable


@dataclass(frozen=True, slots=True)
class TimezoneValue:
    """Value object for timezone write."""

    user_id: int
    offset: str


@final
class TimezoneStore(Readable[int, str | None], Writable[TimezoneValue, None]):
    """In-memory store: user_id → offset string (e.g. ``'UTC+5'``)."""

    def __init__(self) -> None:
        """Init."""
        self._timezones: dict[int, str] = {}

    # ── Protocol implementations ──────────────────────────────────────

    def read(self, query: int) -> str | None:
        """Read a user's offset string."""
        return self._timezones.get(query)

    def write(self, value: TimezoneValue) -> None:
        """Set a user's offset string."""
        self._timezones[value.user_id] = value.offset

    # ── Domain methods ────────────────────────────────────────────────

    def get(self, user_id: int) -> str | None:
        """Get a user's offset string, or ``None`` if not set."""
        return self.read(user_id)

    def set(self, user_id: int, offset_str: str) -> None:
        """Set a user's offset string."""
        self.write(TimezoneValue(user_id=user_id, offset=offset_str))

    def has(self, user_id: int) -> bool:
        """Check if a user has a timezone set."""
        return user_id in self._timezones

"""Pending confirmation database."""

from dataclasses import dataclass
from dataclasses import replace
from typing import final

from niles.discord.databases import Deletable
from niles.discord.databases import Readable
from niles.discord.databases import Updatable
from niles.discord.databases import Writable
from niles.discord.models import PendingConfirmation
from niles.utils.loggers import LOGGER


@dataclass(frozen=True, slots=True)
class ByKey:
    """Query by event_id and action."""

    event_id: str
    action: str


type _PendingReadQuery = ByKey
type _PendingReadResult = PendingConfirmation | None
type _PendingDeleteQuery = ByKey


@final
class PendingConfirmationStore(
    Readable[_PendingReadQuery, _PendingReadResult],
    Writable[PendingConfirmation, None],
    Deletable[_PendingDeleteQuery, None],
    Updatable[ByKey, PendingConfirmation, PendingConfirmation | None],
):
    """In-memory store for pending confirmations."""

    def __init__(self) -> None:
        """Init."""
        self._entries: dict[str, PendingConfirmation] = {}

    def _key(self, event_id: str, action: str) -> str:
        return f"{event_id}:{action}"

    # ── Protocol implementations ──────────────────────────────────────

    def write(self, value: PendingConfirmation) -> None:
        """Register a pending confirmation."""
        key = self._key(value.event_id, value.action)
        self._entries[key] = value

    def read(self, query: ByKey) -> PendingConfirmation | None:
        """Get a pending confirmation."""
        return self._entries.get(self._key(query.event_id, query.action))

    def delete(self, query: ByKey) -> None:
        """Remove a pending confirmation."""
        self._entries.pop(self._key(query.event_id, query.action), None)

    def update(
        self, query: ByKey, value: PendingConfirmation
    ) -> PendingConfirmation | None:
        """Replace a pending confirmation by key."""
        key = self._key(query.event_id, query.action)
        if key not in self._entries:
            return None
        self._entries[key] = value
        return value

    # ── Domain methods ────────────────────────────────────────────────

    def register(self, pending: PendingConfirmation) -> None:
        """Register a pending confirmation."""
        self.write(pending)
        LOGGER.debug(
            "Pending {} for event {} registered (target={})",
            pending.action,
            pending.event_id,
            pending.target_user_id,
        )

    def get(self, event_id: str, action: str) -> PendingConfirmation | None:
        """Get a pending confirmation."""
        return self.read(ByKey(event_id=event_id, action=action))

    def remove(self, event_id: str, action: str) -> None:
        """Remove a pending confirmation."""
        self.delete(ByKey(event_id=event_id, action=action))
        LOGGER.debug("Pending {} for event {} removed", action, event_id)

    def record_vote(
        self, event_id: str, action: str, mod_id: int, vote: str
    ) -> PendingConfirmation | None:
        """Record a moderator vote."""
        pending = self.read(ByKey(event_id=event_id, action=action))
        if pending is None:
            return None
        new_votes = {**pending.votes, mod_id: vote}
        updated = replace(pending, votes=new_votes)
        return self.update(ByKey(event_id=event_id, action=action), updated)

    def reject_with_reason(
        self, event_id: str, action: str, mod_id: int, reason: str
    ) -> PendingConfirmation | None:
        """Record a rejection with reason."""
        pending = self.read(ByKey(event_id=event_id, action=action))
        if pending is None:
            return None
        new_votes = {**pending.votes, mod_id: "no"}
        updated = replace(pending, votes=new_votes, reason=reason)
        self.update(ByKey(event_id=event_id, action=action), updated)
        return updated

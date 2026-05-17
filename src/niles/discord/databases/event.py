"""Event database."""

from dataclasses import dataclass
from typing import final

from niles.discord.databases import Readable
from niles.discord.databases import Updatable
from niles.discord.databases import Writable
from niles.discord.models import EventData
from niles.utils.loggers import LOGGER


@dataclass(frozen=True, slots=True)
class ByEventId:
    """Query a single event by its ID."""

    id: str


@dataclass(frozen=True, slots=True)
class AllEvents:
    """Query all events."""


type _EventReadQuery = ByEventId | AllEvents
type _EventReadResult = EventData | list[EventData] | None


@final
class EventStore(
    Readable[_EventReadQuery, _EventReadResult],
    Writable[EventData, EventData],
    Updatable[ByEventId, EventData, EventData],
):
    """In-memory store for events."""

    def __init__(self) -> None:
        """Init."""
        self._events: dict[str, EventData] = {}

    # ── Protocol implementations ──────────────────────────────────────

    def write(self, value: EventData) -> EventData:
        """Store an event."""
        self._events[value.id] = value
        return value

    def read(self, query: _EventReadQuery) -> _EventReadResult:
        """Read events by query type."""
        match query:
            case ByEventId(eid):
                return self._events.get(eid)
            case AllEvents():
                return list(self._events.values())
            case _:
                return None

    def update(self, query: ByEventId, value: EventData) -> EventData:
        """Replace an event by ID."""
        self._events[query.id] = value
        return value

    # ── Domain methods ────────────────────────────────────────────────

    def create_event(self, event: EventData) -> EventData:
        """Create a new event."""
        self.write(event)
        LOGGER.info(
            "Event created: {} (id={}, creator={})",
            event.name,
            event.id,
            event.creator_id,
        )
        return event

    def get_event(self, event_id: str) -> EventData | None:
        """Get an event by ID."""
        event = self.read(ByEventId(event_id))
        if isinstance(event, EventData):
            return event
        return None

    def get_all_events(self) -> list[EventData]:
        """Get all events."""
        result = self.read(AllEvents())
        return result if isinstance(result, list) else []

    def update_event(self, event: EventData) -> EventData:
        """Update an event (replace by ID)."""
        self.update(ByEventId(event.id), event)
        LOGGER.debug("Event {} updated (closed={})", event.id, event.is_closed)
        return event

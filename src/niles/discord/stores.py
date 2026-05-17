"""Data stores — re-exports from database modules."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord

from niles.discord.databases.event import EventStore
from niles.discord.databases.pending import PendingConfirmationStore
from niles.discord.databases.schedule import ScheduleStore
from niles.discord.databases.timezone import TimezoneStore

__all__ = [
    "EventStore",
    "PendingConfirmationStore",
    "ScheduleStore",
    "TimezoneStore",
    "get_event_store",
    "get_pending_confirmation_store",
    "get_schedule_store",
    "get_timezone_store",
]


def get_schedule_store(
    interaction: discord.Interaction,
) -> ScheduleStore | None:
    """Get the ScheduleStore from the client."""
    client = interaction.client
    store = getattr(client, "schedules", None)
    if isinstance(store, ScheduleStore):
        return store
    return None


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

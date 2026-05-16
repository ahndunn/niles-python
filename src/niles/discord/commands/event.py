"""Event commands."""
# pyright: reportMissingTypeArgument=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import contextlib
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import discord
from discord import Interaction
from discord import app_commands
from discord.ui import Modal
from discord.ui import TextInput

from niles.discord.models import EventData
from niles.discord.models import TimeWindow
from niles.discord.stores import get_event_store
from niles.discord.stores import get_schedule_store
from niles.discord.views import EventRoleSelectView
from niles.discord.views import EventSelectView
from niles.discord.views import ensure_timezone
from niles.utils.loggers import LOGGER

event_group = app_commands.Group(name="event", description="Manage events")


class CreateEventModal(Modal):
    """Modal for creating an event."""

    def __init__(self, offset: timedelta) -> None:
        """Init."""
        super().__init__(title="Create Event")
        self._offset = offset
        now = datetime.now(UTC).astimezone(timezone(offset))
        self._name: TextInput = TextInput(
            label="Event Name", placeholder="Enter event name", required=True
        )
        self._year: TextInput = TextInput(
            label="Year",
            placeholder="2024",
            default=str(now.year),
            required=True,
            min_length=4,
            max_length=4,
        )
        self._month: TextInput = TextInput(
            label="Month",
            placeholder="1-12",
            default=str(now.month),
            required=True,
            min_length=1,
            max_length=2,
        )
        self._day: TextInput = TextInput(
            label="Day",
            placeholder="1-31",
            default=str(now.day),
            required=True,
            min_length=1,
            max_length=2,
        )
        self._start_time: TextInput = TextInput(
            label="Start Time", placeholder="HH:MM (24h)", required=True
        )
        self._end_time: TextInput = TextInput(
            label="End Time", placeholder="HH:MM (24h)", required=True
        )
        self.add_item(self._name)
        self.add_item(self._year)
        self.add_item(self._month)
        self.add_item(self._day)
        self.add_item(self._start_time)
        self.add_item(self._end_time)

    async def on_submit(self, interaction: Interaction) -> None:  # noqa: C901
        """Handle event creation submission."""
        try:
            sy = int(self._year.value)
            sm = int(self._month.value)
            sd = int(self._day.value)
            sh, smi = (int(x) for x in self._start_time.value.split(":"))
            eh, emi = (int(x) for x in self._end_time.value.split(":"))
        except ValueError as e:
            LOGGER.warning(
                "Invalid date/time in CreateEventModal from user {}: {}",
                interaction.user.id,
                e,
            )
            await interaction.response.send_message(
                f"Invalid date/time: {e}", ephemeral=True
            )
            return

        user_tz = timezone(self._offset)
        start = datetime(sy, sm, sd, sh, smi, tzinfo=user_tz).astimezone(UTC)
        end = datetime(sy, sm, sd, eh, emi, tzinfo=user_tz).astimezone(UTC)

        window = TimeWindow(start=start, end=end)
        if window.end <= window.start:
            LOGGER.warning(
                "End time before start time in CreateEventModal from user {}",
                interaction.user.id,
            )
            await interaction.response.send_message(
                "End time must be after start time.", ephemeral=True
            )
            return

        schedule_store = get_schedule_store(interaction)
        free_user_ids: set[int] = set()
        if schedule_store is not None:
            free_user_ids = schedule_store.get_free_user_ids(window)

        event = EventData(
            name=self._name.value,
            creator_id=interaction.user.id,
            guild_id=interaction.guild_id or 0,
            window=window,
            participant_ids=(interaction.user.id, *free_user_ids),
            moderator_ids=(interaction.user.id,),
        )

        store = get_event_store(interaction)
        if store is None:
            LOGGER.error(
                "EventStore unavailable for user {} during event creation",
                interaction.user.id,
            )
            await interaction.response.send_message(
                "Store not available.", ephemeral=True
            )
            return

        if interaction.guild is None:
            LOGGER.warning(
                "Event creation attempted outside guild by user {}",
                interaction.user.id,
            )
            await interaction.response.send_message(
                "Must be used in a guild.", ephemeral=True
            )
            return

        guild = interaction.guild

        parent = guild.system_channel or next(
            (
                ch
                for ch in guild.text_channels
                if ch.permissions_for(guild.me).send_messages
            ),
            None,
        )
        if parent is None:
            LOGGER.error(
                "No suitable channel for threads in guild {} for user {}",
                guild.id,
                interaction.user.id,
            )
            await interaction.response.send_message(
                "No suitable channel found for creating threads.",
                ephemeral=True,
            )
            return

        part_thread = await parent.create_thread(
            name=f"event-{event.name[:80]}",
            type=discord.ChannelType.private_thread,
        )
        mod_thread = await parent.create_thread(
            name=f"mod-{event.name[:80]}",
            type=discord.ChannelType.private_thread,
        )

        event = EventData(
            id=event.id,
            name=event.name,
            creator_id=event.creator_id,
            guild_id=event.guild_id,
            window=event.window,
            participant_ids=event.participant_ids,
            moderator_ids=event.moderator_ids,
            participant_thread_id=part_thread.id,
            moderator_thread_id=mod_thread.id,
        )
        store.create_event(event)

        for pid in event.participant_ids:
            member = guild.get_member(pid)
            if member is not None:
                with contextlib.suppress(
                    discord.Forbidden, discord.HTTPException
                ):
                    await part_thread.add_user(member)

        for mid in event.moderator_ids:
            member = guild.get_member(mid)
            if member is not None:
                with contextlib.suppress(
                    discord.Forbidden, discord.HTTPException
                ):
                    await mod_thread.add_user(member)

        LOGGER.info(
            "Event '{}' (id={}) created by user {} "
            "with {} participants, {} mods, {} free users auto-added",
            event.name,
            event.id,
            interaction.user.id,
            len(event.participant_ids),
            len(event.moderator_ids),
            len(free_user_ids),
        )

        free_names = " ".join(f"<@{uid}>" for uid in free_user_ids)
        await interaction.response.send_message(
            f"Created event **{event.name}**!\n"
            f"Free users in this window: {free_names}\n"
            f"Mod thread: {mod_thread.mention}\n"
            f"Event thread: {part_thread.mention}",
            ephemeral=True,
        )


@event_group.command(
    name="create", description="Create an event on a free time window"
)
async def event_create(interaction: Interaction) -> None:
    """Create a new event."""
    offset = await ensure_timezone(interaction)
    if offset is None:
        return
    LOGGER.info("User {} used /event create", interaction.user.id)
    modal = CreateEventModal(offset)
    await interaction.response.send_modal(modal)


@event_group.command(
    name="add", description="Add a moderator or participant to an event"
)
async def event_add(interaction: Interaction, user: discord.User) -> None:
    """Add a moderator or participant to an event (with event picker)."""
    LOGGER.info(
        "User {} used /event add targeting {}", interaction.user.id, user.id
    )
    store = get_event_store(interaction)
    if store is None:
        await interaction.response.send_message(
            "Store not available.", ephemeral=True
        )
        return
    view = EventRoleSelectView("add", user)
    await interaction.response.send_message(
        f"Select role for {user.mention}:", view=view, ephemeral=True
    )


@event_group.command(
    name="remove", description="Remove a moderator or participant from an event"
)
async def event_remove(interaction: Interaction, user: discord.User) -> None:
    """Remove a moderator or participant from an event (with event picker)."""
    LOGGER.info(
        "User {} used /event remove targeting {}", interaction.user.id, user.id
    )
    store = get_event_store(interaction)
    if store is None:
        await interaction.response.send_message(
            "Store not available.", ephemeral=True
        )
        return
    view = EventRoleSelectView("remove", user)
    await interaction.response.send_message(
        f"Select role for {user.mention}:", view=view, ephemeral=True
    )


@event_group.command(name="close", description="Close an event")
async def event_close(interaction: Interaction) -> None:
    """Close an event with all moderator confirmation (with event picker)."""
    LOGGER.info("User {} used /event close", interaction.user.id)
    store = get_event_store(interaction)
    if store is None:
        await interaction.response.send_message(
            "Store not available.", ephemeral=True
        )
        return
    view = EventSelectView(interaction, "close", target_user=None, role=None)
    await interaction.response.send_message(
        "Select an event to close:", view=view, ephemeral=True
    )

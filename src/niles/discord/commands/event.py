"""Event commands."""
# pyright: reportMissingTypeArgument=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import contextlib
from datetime import UTC
from datetime import datetime

import discord
from discord import Interaction
from discord import app_commands
from discord.ui import Modal
from discord.ui import TextInput

from niles.discord.models import EventData
from niles.discord.models import TimeWindow
from niles.discord.stores import get_event_store
from niles.discord.stores import get_schedule_store
from niles.discord.views import ModConfirmationView
from niles.discord.views import ModInvitationView
from niles.utils.loggers import LOGGER

event_group = app_commands.Group(name="event", description="Manage events")


class CreateEventModal(Modal):
    """Modal for creating an event."""

    def __init__(self) -> None:
        """Init."""
        super().__init__(title="Create Event")
        self._name: TextInput = TextInput(
            label="Event Name", placeholder="Enter event name", required=True
        )
        self._date: TextInput = TextInput(
            label="Date", placeholder="YYYY-MM-DD", required=True
        )
        self._start_time: TextInput = TextInput(
            label="Start Time", placeholder="HH:MM (24h)", required=True
        )
        self._end_time: TextInput = TextInput(
            label="End Time", placeholder="HH:MM (24h)", required=True
        )
        self._date: TextInput = TextInput(
            label="Date", placeholder="YYYY-MM-DD", required=True
        )
        self._start_time: TextInput = TextInput(
            label="Start Time", placeholder="HH:MM (24h)", required=True
        )
        self._end_time: TextInput = TextInput(
            label="End Time", placeholder="HH:MM (24h)", required=True
        )
        self.add_item(self._name)
        self.add_item(self._date)
        self.add_item(self._start_time)
        self.add_item(self._end_time)

    async def on_submit(self, interaction: Interaction) -> None:  # noqa: C901
        """Handle event creation submission."""
        try:
            sdate = datetime.strptime(self._date.value, "%Y-%m-%d").replace(
                tzinfo=UTC
            )
            stime = datetime.strptime(self._start_time.value, "%H:%M").time()  # noqa: DTZ007
            etime = datetime.strptime(self._end_time.value, "%H:%M").time()  # noqa: DTZ007
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

        window = TimeWindow(
            start=sdate.replace(hour=stime.hour, minute=stime.minute),
            end=sdate.replace(hour=etime.hour, minute=etime.minute),
        )
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
    LOGGER.info("User {} used /event create", interaction.user.id)
    modal = CreateEventModal()
    await interaction.response.send_modal(modal)


@event_group.command(name="add-mod", description="Add a moderator to an event")
async def event_add_mod(
    interaction: Interaction, event: str, user: discord.User
) -> None:
    """Send a moderator invitation to a user."""
    LOGGER.info(
        "User {} used /event add-mod targeting {}", interaction.user.id, user.id
    )
    store = get_event_store(interaction)
    if store is None:
        LOGGER.error(
            "EventStore unavailable for user {} in /event add-mod",
            interaction.user.id,
        )
        await interaction.response.send_message(
            "Store not available.", ephemeral=True
        )
        return
    ev = store.get_event(event)
    if ev is None:
        LOGGER.warning(
            "Event {} not found for user {} in /event add-mod",
            event,
            interaction.user.id,
        )
        await interaction.response.send_message(
            "Event not found.", ephemeral=True
        )
        return
    if interaction.user.id != ev.creator_id:
        LOGGER.warning(
            "User {} is not creator of event {} attempted /event add-mod",
            interaction.user.id,
            event,
        )
        await interaction.response.send_message(
            "Only the event creator can add moderators.", ephemeral=True
        )
        return
    if user.id in ev.moderator_ids:
        LOGGER.warning(
            "User {} is already a moderator of event {}", user.id, event
        )
        await interaction.response.send_message(
            "User is already a moderator.", ephemeral=True
        )
        return
    view = ModInvitationView(ev.id, user.id, ev.guild_id)
    with contextlib.suppress(discord.Forbidden):
        await user.send(
            f"You've been invited to moderate **{ev.name}**!", view=view
        )
    LOGGER.info(
        "Mod invitation sent to user {} for event {} by user {}",
        user.id,
        event,
        interaction.user.id,
    )
    await interaction.response.send_message(
        f"Invitation sent to {user.mention}.", ephemeral=True
    )


@event_group.command(
    name="remove-mod", description="Remove a moderator from an event"
)
async def event_remove_mod(
    interaction: Interaction, event: str, user: discord.User, why: str
) -> None:
    """Remove a moderator from an event."""
    LOGGER.info(
        "User {} used /event remove-mod targeting {}",
        interaction.user.id,
        user.id,
    )
    store = get_event_store(interaction)
    if store is None:
        LOGGER.error(
            "EventStore unavailable for user {} in /event remove-mod",
            interaction.user.id,
        )
        await interaction.response.send_message(
            "Store not available.", ephemeral=True
        )
        return
    ev = store.get_event(event)
    if ev is None:
        LOGGER.warning(
            "Event {} not found for user {} in /event remove-mod",
            event,
            interaction.user.id,
        )
        await interaction.response.send_message(
            "Event not found.", ephemeral=True
        )
        return
    if interaction.user.id != ev.creator_id:
        LOGGER.warning(
            "User {} is not creator of event {} attempted /event remove-mod",
            interaction.user.id,
            event,
        )
        await interaction.response.send_message(
            "Only the event creator can remove moderators.", ephemeral=True
        )
        return
    if user.id not in ev.moderator_ids:
        LOGGER.warning("User {} is not a moderator of event {}", user.id, event)
        await interaction.response.send_message(
            "User is not a moderator.", ephemeral=True
        )
        return
    new_mods = tuple(mid for mid in ev.moderator_ids if mid != user.id)
    updated = EventData(
        id=ev.id,
        name=ev.name,
        creator_id=ev.creator_id,
        guild_id=ev.guild_id,
        window=ev.window,
        participant_ids=ev.participant_ids,
        moderator_ids=new_mods,
        participant_thread_id=ev.participant_thread_id,
        moderator_thread_id=ev.moderator_thread_id,
        is_closed=ev.is_closed,
        created_at=ev.created_at,
    )
    store.update_event(updated)

    if ev.moderator_thread_id and interaction.guild:
        mod_thread = interaction.guild.get_thread(ev.moderator_thread_id)
        if mod_thread is not None:
            await mod_thread.send(
                f"<@{user.id}> has been removed as moderator. Reason: {why}"
            )

    LOGGER.info(
        "Moderator {} removed from event {} by user {} (reason={})",
        user.id,
        event,
        interaction.user.id,
        why,
    )
    await interaction.response.send_message(
        f"Removed {user.mention} from moderators.", ephemeral=True
    )


@event_group.command(name="add-user", description="Add a user to an event")
async def event_add_user(
    interaction: Interaction, event: str, user: discord.User
) -> None:
    """Propose adding a user to an event."""
    LOGGER.info(
        "User {} used /event add-user targeting {} for event {}",
        interaction.user.id,
        user.id,
        event,
    )
    store = get_event_store(interaction)
    if store is None:
        LOGGER.error(
            "EventStore unavailable for user {} in /event add-user",
            interaction.user.id,
        )
        await interaction.response.send_message(
            "Store not available.", ephemeral=True
        )
        return
    ev = store.get_event(event)
    if ev is None:
        LOGGER.warning(
            "Event {} not found for user {} in /event add-user",
            event,
            interaction.user.id,
        )
        await interaction.response.send_message(
            "Event not found.", ephemeral=True
        )
        return
    if interaction.user.id not in ev.moderator_ids:
        LOGGER.warning(
            "User {} is not a moderator of event {} attempted /event add-user",
            interaction.user.id,
            event,
        )
        await interaction.response.send_message(
            "Only moderators can add users.", ephemeral=True
        )
        return
    if user.id in ev.participant_ids:
        LOGGER.warning(
            "User {} is already a participant of event {}", user.id, event
        )
        await interaction.response.send_message(
            "User is already participating.", ephemeral=True
        )
        return

    schedule_store = get_schedule_store(interaction)
    if schedule_store is not None:
        free_ids = schedule_store.get_free_user_ids(ev.window)
        if user.id not in free_ids:
            LOGGER.warning(
                "User {} is occupied and cannot be added to event {}",
                user.id,
                event,
            )
            await interaction.response.send_message(
                "Cannot add an occupied user to this event.", ephemeral=True
            )
            return

    mod_ids = list(ev.moderator_ids)
    view = ModConfirmationView(
        event_id=ev.id,
        action="add_user",
        reason=None,
        target_user_id=user.id,
        moderator_ids=mod_ids,
        guild_id=ev.guild_id,
    )
    LOGGER.info(
        "Add-user proposal for event {} targeting {} initiated by user {}",
        event,
        user.id,
        interaction.user.id,
    )
    await interaction.response.send_message(
        f"Proposal to add {user.mention} to **{ev.name}**.\n"
        f"Moderators, please vote:",
        view=view,
    )


@event_group.command(
    name="remove-user", description="Remove a user from an event"
)
async def event_remove_user(
    interaction: Interaction, event: str, user: discord.User, reason: str
) -> None:
    """Propose removing a user from an event."""
    LOGGER.info(
        "User {} used /event remove-user targeting {} for event {}",
        interaction.user.id,
        user.id,
        event,
    )
    store = get_event_store(interaction)
    if store is None:
        LOGGER.error(
            "EventStore unavailable for user {} in /event remove-user",
            interaction.user.id,
        )
        await interaction.response.send_message(
            "Store not available.", ephemeral=True
        )
        return
    ev = store.get_event(event)
    if ev is None:
        LOGGER.warning(
            "Event {} not found for user {} in /event remove-user",
            event,
            interaction.user.id,
        )
        await interaction.response.send_message(
            "Event not found.", ephemeral=True
        )
        return
    if interaction.user.id not in ev.moderator_ids:
        LOGGER.warning(
            "User {} is not a mod of event {} attempted /event remove-user",
            interaction.user.id,
            event,
        )
        await interaction.response.send_message(
            "Only moderators can remove users.", ephemeral=True
        )
        return
    if user.id not in ev.participant_ids:
        LOGGER.warning(
            "User {} is not a participant of event {}", user.id, event
        )
        await interaction.response.send_message(
            "User is not participating.", ephemeral=True
        )
        return

    mod_ids = list(ev.moderator_ids)
    view = ModConfirmationView(
        event_id=ev.id,
        action="remove_user",
        reason=reason,
        target_user_id=user.id,
        moderator_ids=mod_ids,
        guild_id=ev.guild_id,
    )
    LOGGER.info(
        "Remove-user proposal for event {} targeting {} "
        "initiated by user {} (reason={})",
        event,
        user.id,
        interaction.user.id,
        reason,
    )
    await interaction.response.send_message(
        f"Proposal to remove {user.mention} from **{ev.name}**.\n"
        f"Reason: {reason}\n"
        f"Moderators, please vote:",
        view=view,
    )


@event_group.command(name="close", description="Close an event")
async def event_close(interaction: Interaction, event: str) -> None:
    """Close an event with all moderator confirmation."""
    LOGGER.info(
        "User {} used /event close for event {}", interaction.user.id, event
    )
    store = get_event_store(interaction)
    if store is None:
        LOGGER.error(
            "EventStore unavailable for user {} in /event close",
            interaction.user.id,
        )
        await interaction.response.send_message(
            "Store not available.", ephemeral=True
        )
        return
    ev = store.get_event(event)
    if ev is None:
        LOGGER.warning(
            "Event {} not found for user {} in /event close",
            event,
            interaction.user.id,
        )
        await interaction.response.send_message(
            "Event not found.", ephemeral=True
        )
        return
    if interaction.user.id not in ev.moderator_ids:
        LOGGER.warning(
            "User {} is not a moderator of event {} attempted /event close",
            interaction.user.id,
            event,
        )
        await interaction.response.send_message(
            "Only moderators can close events.", ephemeral=True
        )
        return
    if ev.is_closed:
        LOGGER.warning(
            "Event {} is already closed, close attempted by user {}",
            event,
            interaction.user.id,
        )
        await interaction.response.send_message(
            "Event is already closed.", ephemeral=True
        )
        return

    mod_ids = list(ev.moderator_ids)
    view = ModConfirmationView(
        event_id=ev.id,
        action="close",
        reason=None,
        target_user_id=None,
        moderator_ids=mod_ids,
        guild_id=ev.guild_id,
    )
    LOGGER.info(
        "Close proposal for event {} initiated by user {}",
        event,
        interaction.user.id,
    )
    await interaction.response.send_message(
        f"Proposal to close **{ev.name}**.\n"
        f"All moderators must approve (no timeout):",
        view=view,
    )

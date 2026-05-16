"""Event commands."""

import calendar
import contextlib
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import cast

import discord
from discord import Interaction
from discord import app_commands
from discord.ui import Button
from discord.ui import Select
from discord.ui import View

from niles.discord.models import EventData
from niles.discord.models import TimeWindow
from niles.discord.stores import get_event_store
from niles.discord.stores import get_schedule_store
from niles.discord.views import EventRoleSelectView
from niles.discord.views import EventSelectView
from niles.discord.views import ensure_timezone
from niles.utils.loggers import LOGGER

event_group = app_commands.Group(name="event", description="Manage events")


class EventNameStep(View):
    """Step 1: collect event name via chat input."""

    def __init__(self, offset: timedelta) -> None:  # noqa: D107
        super().__init__(timeout=120)
        self._offset = offset

    @discord.ui.button(label="Start", style=discord.ButtonStyle.primary)
    async def start_btn(  # noqa: D102
        self, interaction: Interaction, _button: Button[Any]
    ) -> None:
        for child in self.children:
            cast("Any", child).disabled = True
        await interaction.response.edit_message(
            content="**Step 1/7: Event Name**\nType the event name below:",
            view=self,
        )

        def check(msg: discord.Message) -> bool:
            return (
                msg.author == interaction.user
                and msg.channel == interaction.channel
            )

        try:
            msg = await interaction.client.wait_for(
                "message", check=check, timeout=120.0
            )
        except TimeoutError:
            await interaction.followup.send(
                "Timed out. Use `/event create` to start over.", ephemeral=True
            )
            return

        name = msg.content.strip()
        if not name:
            await interaction.followup.send(
                "Name cannot be empty. Use `/event create` to start over.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"Name set to **{name}**.", ephemeral=True
        )
        now = datetime.now(UTC).astimezone(timezone(self._offset))
        await interaction.followup.send(
            "**Step 2/7: Event Year**\nSelect the year:",
            view=EventYearSelect(self._offset, name, now.year),
            ephemeral=True,
        )


class EventYearSelect(View):
    """Step 2: select year."""

    def __init__(self, offset: timedelta, name: str, current_year: int) -> None:  # noqa: D107
        super().__init__(timeout=120)
        self._offset = offset
        self._name = name
        options = [
            discord.SelectOption(label=str(y), value=str(y))
            for y in range(current_year, current_year + 5)
        ]
        sel: Select[Any] = Select(
            options=options, placeholder="Select year", row=0
        )
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: Interaction) -> None:
        val = _first_val(interaction)
        if val is None:
            return
        await interaction.response.edit_message(
            content=f"Year set to **{val}**.",
            view=EventMonthSelect(self._offset, self._name, int(val)),
        )


class EventMonthSelect(View):
    """Step 3: select month."""

    def __init__(self, offset: timedelta, name: str, year: int) -> None:  # noqa: D107
        super().__init__(timeout=120)
        self._offset = offset
        self._name = name
        self._year = year
        options = [
            discord.SelectOption(label=str(m), value=str(m))
            for m in range(1, 13)
        ]
        sel: Select[Any] = Select(
            options=options, placeholder="Select month (1-12)", row=0
        )
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: Interaction) -> None:
        val = _first_val(interaction)
        if val is None:
            return
        await interaction.response.edit_message(
            content=f"Month set to **{val}**.",
            view=EventDaySelect(self._offset, self._name, self._year, int(val)),
        )


class EventDaySelect(View):
    """Step 4: select day."""

    def __init__(  # noqa: D107
        self, offset: timedelta, name: str, year: int, month: int
    ) -> None:
        super().__init__(timeout=120)
        self._offset = offset
        self._name = name
        self._year = year
        self._month = month
        max_day = calendar.monthrange(year, month)[1]
        options = [
            discord.SelectOption(label=str(d), value=str(d))
            for d in range(1, max_day + 1)
        ]
        sel: Select[Any] = Select(
            options=options, placeholder="Select day", row=0
        )
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: Interaction) -> None:
        val = _first_val(interaction)
        if val is None:
            return
        await interaction.response.edit_message(
            content=f"Day set to **{val}**.",
            view=EventStartTimeSelect(
                self._offset, self._name, self._year, self._month, int(val)
            ),
        )


class EventStartTimeSelect(View):
    """Step 5: select start hour and minute."""

    def __init__(  # noqa: D107
        self, offset: timedelta, name: str, year: int, month: int, day: int
    ) -> None:
        super().__init__(timeout=120)
        self._offset = offset
        self._name = name
        self._year = year
        self._month = month
        self._day = day
        self._start_h: int | None = None
        self._start_m: int | None = None

        hour_options = [
            discord.SelectOption(label=f"{h:02d}", value=str(h))
            for h in range(24)
        ]
        self._hour_sel: Select[Any] = Select(
            options=hour_options, placeholder="Start hour", row=0
        )
        self._hour_sel.callback = self._on_hour
        self.add_item(self._hour_sel)

        minute_options = [
            discord.SelectOption(label=f"{m:02d}", value=str(m))
            for m in (0, 15, 30, 45)
        ]
        self._min_sel: Select[Any] = Select(
            options=minute_options, placeholder="Start minute", row=1
        )
        self._min_sel.callback = self._on_minute
        self.add_item(self._min_sel)

    async def _on_hour(self, interaction: Interaction) -> None:
        self._start_h = int(self._hour_sel.values[0])
        await self._maybe_advance_start(interaction)

    async def _on_minute(self, interaction: Interaction) -> None:
        self._start_m = int(self._min_sel.values[0])
        await self._maybe_advance_start(interaction)

    async def _maybe_advance_start(self, interaction: Interaction) -> None:
        if self._start_h is None or self._start_m is None:
            await interaction.response.defer()
            return
        await interaction.response.edit_message(
            content=(
                f"Start time set to **{self._start_h:02d}:{self._start_m:02d}**.\n"  # noqa: E501
                "**Step 6/7:** Select end time:"
            ),
            view=EventEndTimeSelect(
                self._offset,
                self._name,
                self._year,
                self._month,
                self._day,
                self._start_h,
                self._start_m,
            ),
        )


class EventEndTimeSelect(View):
    """Step 6: select end hour and minute."""

    def __init__(  # noqa: D107, PLR0913
        self,
        offset: timedelta,
        name: str,
        year: int,
        month: int,
        day: int,
        start_h: int,
        start_m: int,
    ) -> None:
        super().__init__(timeout=120)
        self._offset = offset
        self._name = name
        self._year = year
        self._month = month
        self._day = day
        self._start_h = start_h
        self._start_m = start_m
        self._end_h: int | None = None
        self._end_m: int | None = None

        hour_options = [
            discord.SelectOption(label=f"{h:02d}", value=str(h))
            for h in range(24)
        ]
        self._hour_sel: Select[Any] = Select(
            options=hour_options, placeholder="End hour", row=0
        )
        self._hour_sel.callback = self._on_hour
        self.add_item(self._hour_sel)

        minute_options = [
            discord.SelectOption(label=f"{m:02d}", value=str(m))
            for m in (0, 15, 30, 45)
        ]
        self._min_sel: Select[Any] = Select(
            options=minute_options, placeholder="End minute", row=1
        )
        self._min_sel.callback = self._on_minute
        self.add_item(self._min_sel)

    async def _on_hour(self, interaction: Interaction) -> None:
        self._end_h = int(self._hour_sel.values[0])
        await self._maybe_advance_end(interaction)

    async def _on_minute(self, interaction: Interaction) -> None:
        self._end_m = int(self._min_sel.values[0])
        await self._maybe_advance_end(interaction)

    async def _maybe_advance_end(self, interaction: Interaction) -> None:
        if self._end_h is None or self._end_m is None:
            await interaction.response.defer()
            return
        user_tz = timezone(self._offset)
        start = datetime(
            self._year,
            self._month,
            self._day,
            self._start_h,
            self._start_m,
            tzinfo=user_tz,
        ).astimezone(UTC)
        end = datetime(
            self._year,
            self._month,
            self._day,
            self._end_h,
            self._end_m,
            tzinfo=user_tz,
        ).astimezone(UTC)
        window = TimeWindow(start=start, end=end)

        if window.end <= window.start:
            await interaction.response.edit_message(
                content="End time must be after start time. **Step 6/7:** Select end time:",  # noqa: E501
                view=EventEndTimeSelect(
                    self._offset,
                    self._name,
                    self._year,
                    self._month,
                    self._day,
                    self._start_h,
                    self._start_m,
                ),
            )
            return

        await interaction.response.edit_message(
            content=(
                f"End time set to **{self._end_h:02d}:{self._end_m:02d}**.\n"
                "**Step 7/7: Confirm** — Review your event below."
            ),
            view=EventConfirmView(self._offset, self._name, window),
        )


class EventConfirmView(View):
    """Step 7: review and create event."""

    def __init__(  # noqa: D107
        self, offset: timedelta, name: str, window: TimeWindow
    ) -> None:
        super().__init__(timeout=120)
        self._offset = offset
        self._name = name
        self._window = window
        user_tz = timezone(offset)
        local_start = window.start.astimezone(user_tz)
        local_end = window.end.astimezone(user_tz)
        self._summary = (
            f"**Name:** {name}\n"
            f"**Date:** {local_start.strftime('%A %Y-%m-%d')}\n"
            f"**Time:** {local_start.strftime('%H:%M')} – {local_end.strftime('%H:%M')}"  # noqa: E501, RUF001
        )

    @discord.ui.button(label="Create Event", style=discord.ButtonStyle.success)
    async def create_btn(  # noqa: D102
        self, interaction: Interaction, _button: Button[Any]
    ) -> None:
        for child in self.children:
            cast("Any", child).disabled = True

        schedule_store = get_schedule_store(interaction)
        free_user_ids: set[int] = set()
        if schedule_store is not None:
            free_user_ids = schedule_store.get_free_user_ids(self._window)

        event = EventData(
            name=self._name,
            creator_id=interaction.user.id,
            guild_id=interaction.guild_id or 0,
            window=self._window,
            participant_ids=(interaction.user.id, *free_user_ids),
            moderator_ids=(interaction.user.id,),
        )

        result = await _finalize_event(event, interaction)
        if result is None:
            await interaction.response.edit_message(
                content="Failed to create event. See logs for details.",
                view=self,
            )
            return

        part_thread, mod_thread = result

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
        await interaction.response.edit_message(
            content=(
                f"Created event **{event.name}**!\n"
                f"Free users in this window: {free_names}\n"
                f"Mod thread: {mod_thread.mention}\n"
                f"Event thread: {part_thread.mention}"
            ),
            view=self,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel_btn(  # noqa: D102
        self, interaction: Interaction, _button: Button[Any]
    ) -> None:
        for child in self.children:
            cast("Any", child).disabled = True
        await interaction.response.edit_message(
            content="Event creation cancelled.", view=self
        )


async def _finalize_event(
    event: EventData, interaction: Interaction
) -> tuple[discord.Thread, discord.Thread] | None:
    """Create threads, store event, add members."""
    store = get_event_store(interaction)
    if store is None:
        LOGGER.error(
            "EventStore unavailable for user {} during event creation",
            interaction.user.id,
        )
        await interaction.response.send_message(
            "Store not available.", ephemeral=True
        )
        return None

    if interaction.guild is None:
        LOGGER.warning(
            "Event creation attempted outside guild by user {}",
            interaction.user.id,
        )
        await interaction.response.send_message(
            "Must be used in a guild.", ephemeral=True
        )
        return None

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
            "No suitable channel found for creating threads.", ephemeral=True
        )
        return None

    part_thread = await parent.create_thread(
        name=f"event-{event.name[:80]}", type=discord.ChannelType.private_thread
    )
    mod_thread = await parent.create_thread(
        name=f"mod-{event.name[:80]}", type=discord.ChannelType.private_thread
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
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await part_thread.add_user(member)

    for mid in event.moderator_ids:
        member = guild.get_member(mid)
        if member is not None:
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await mod_thread.add_user(member)

    return part_thread, mod_thread


def _first_val(interaction: Interaction) -> str | None:
    """Extract the first selected value from a Select interaction."""
    data = cast("dict[str, Any]", interaction.data)
    for child in data.get("components", []):
        comps = cast("list[dict[str, Any]]", child.get("components", []))
        for comp in comps:
            vals = comp.get("values", [])
            if vals:
                return vals[0]
    return None


@event_group.command(
    name="create", description="Create an event on a free time window"
)
async def event_create(interaction: Interaction) -> None:
    """Create a new event."""

    async def _continue(interaction: Interaction, offset: timedelta) -> None:
        LOGGER.info("User {} used /event create", interaction.user.id)
        await interaction.followup.send(
            "**Let's create an event!** Follow the steps below.\n"
            "**Step 1/7:** What's the event name?\n"
            "Click **Start** below, then type the name in chat.",
            view=EventNameStep(offset),
            ephemeral=True,
        )

    offset = await ensure_timezone(interaction, on_complete=_continue)
    if offset is None:
        return
    await interaction.response.defer(ephemeral=True)
    await _continue(interaction, offset)


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

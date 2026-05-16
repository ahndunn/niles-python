"""Discord UI components."""
# pyright: reportMissingTypeArgument=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import contextlib
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import Any
from typing import Literal
from uuid import uuid4

import discord
from discord import Interaction
from discord.ui import Button
from discord.ui import Modal
from discord.ui import Select
from discord.ui import TextInput
from discord.ui import View

from niles.discord.models import EventData
from niles.discord.models import FreeTimeEntry
from niles.discord.models import TimeWindow
from niles.discord.models import (
    _PendingConfirmation,  # type: ignore[reportPrivateUsage]
)
from niles.discord.models import get_pending
from niles.discord.models import register_pending
from niles.discord.models import remove_pending
from niles.discord.stores import EventStore
from niles.discord.stores import ScheduleStore
from niles.discord.stores import get_event_store

_DAY_NAMES: dict[str, int] = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}

_TIMEOUT_MINUTES = 60
_PREVIEW_LIMIT = 20
_DISCORD_MAX_LINE_LENGTH = 80


def _parse_day_names(raw: str) -> set[int] | None:
    """Parse comma-separated day names into weekday numbers."""
    if not raw.strip():
        return None
    parts = [p.strip().lower()[:3] for p in raw.split(",")]
    result: set[int] = set()
    for p in parts:
        day = _DAY_NAMES.get(p)
        if day is None:
            msg = f"Unknown day: {p}"
            raise ValueError(msg)
        result.add(day)
    return result


def _generate_windows(
    start_date: str, end_date: str, start_time: str, end_time: str, days: str
) -> tuple[TimeWindow, ...]:
    """Generate 15-minute time windows from parameters."""
    sdate = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC)
    edate = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=UTC)
    stime = datetime.strptime(start_time, "%H:%M").time()  # noqa: DTZ007
    etime = datetime.strptime(end_time, "%H:%M").time()  # noqa: DTZ007
    day_filter = _parse_day_names(days)

    windows: list[TimeWindow] = []
    current = sdate
    while current <= edate:
        if day_filter is None or current.weekday() in day_filter:
            win_start = current.replace(
                hour=stime.hour, minute=stime.minute, second=0, microsecond=0
            )
            win_end = current.replace(
                hour=etime.hour, minute=etime.minute, second=0, microsecond=0
            )
            while win_start + timedelta(minutes=15) <= win_end:
                w_end = win_start + timedelta(minutes=15)
                windows.append(TimeWindow(start=win_start, end=w_end))
                win_start = w_end
        current += timedelta(days=1)
    return tuple(windows)


def _fmt_range(w: TimeWindow) -> str:
    """Format a time window as a readable range."""
    return f"{w.start.strftime('%a %Y-%m-%d %H:%M')}-{w.end.strftime('%H:%M')}"


def _fmt_short(w: TimeWindow) -> str:
    """Format a time window as short time range."""
    return f"{w.start.strftime('%H:%M')}-{w.end.strftime('%H:%M')}"


def _compute_timeout(sent_at: datetime | None = None) -> datetime | None:
    """Compute the deadline for a confirmation based on timeout rules.

    The response window is 8:00 to midnight (0:00) of the next day.
    """
    if sent_at is None:
        sent_at = datetime.now(UTC)
    today_8am = sent_at.replace(hour=8, minute=0, second=0, microsecond=0)
    today_midnight = (sent_at + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    next_day_8am = today_midnight.replace(hour=8)

    if sent_at < today_8am:
        return next_day_8am + timedelta(minutes=_TIMEOUT_MINUTES)
    time_until_midnight = (today_midnight - sent_at).total_seconds() / 60
    if time_until_midnight > _TIMEOUT_MINUTES:
        return sent_at + timedelta(minutes=_TIMEOUT_MINUTES)
    remaining = _TIMEOUT_MINUTES - time_until_midnight
    return next_day_8am + timedelta(minutes=remaining)


class ScheduleAddModal(Modal):
    """Modal for adding free time windows."""

    def __init__(self, store: ScheduleStore, user_id: int) -> None:
        """Init."""
        super().__init__(title="Add Free Time")
        self._store = store
        self._user_id = user_id
        self._start_date = TextInput(
            label="Start Date", placeholder="YYYY-MM-DD", required=True
        )
        self._end_date = TextInput(
            label="End Date", placeholder="YYYY-MM-DD", required=True
        )
        self._start_time = TextInput(
            label="Start Time", placeholder="HH:MM (24h)", required=True
        )
        self._end_time = TextInput(
            label="End Time", placeholder="HH:MM (24h)", required=True
        )
        self._days = TextInput(
            label="Days of Week (optional)",
            placeholder="e.g. Mon,Wed,Fri or leave empty for all",
            required=False,
        )
        self.add_item(self._start_date)
        self.add_item(self._end_date)
        self.add_item(self._start_time)
        self.add_item(self._end_time)
        self.add_item(self._days)

    async def on_submit(self, interaction: Interaction) -> None:
        """Handle modal submission."""
        try:
            windows = _generate_windows(
                self._start_date.value,
                self._end_date.value,
                self._start_time.value,
                self._end_time.value,
                self._days.value,
            )
        except ValueError as e:
            await interaction.response.send_message(
                f"Invalid input: {e}", ephemeral=True
            )
            return
        if not windows:
            await interaction.response.send_message(
                "No windows generated. Check your date/time range.",
                ephemeral=True,
            )
            return
        preview_items = windows[:_PREVIEW_LIMIT]
        preview = "\n".join(_fmt_range(w) for w in preview_items)
        if len(windows) > _PREVIEW_LIMIT:
            preview += f"\n... and {len(windows) - _PREVIEW_LIMIT} more"
        view = ConfirmWindowsView(self._store, self._user_id, windows)
        msg = (
            f"Generated {len(windows)} time windows:\n"
            f"```\n{preview}\n```\nConfirm?"
        )
        await interaction.response.send_message(msg, view=view, ephemeral=True)


class ConfirmWindowsView(View):
    """Confirm/cancel generated windows."""

    def __init__(
        self,
        store: ScheduleStore,
        user_id: int,
        windows: tuple[TimeWindow, ...],
    ) -> None:
        """Init."""
        super().__init__(timeout=120)
        self._store = store
        self._user_id = user_id
        self._windows = windows

    async def _disable_all(self, interaction: Interaction) -> None:
        """Disable all children."""
        for child in self.children:
            child.disabled = True  # type: ignore[reportAttributeAccessIssue]
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(
        self, interaction: Interaction, _button: Button[Any]
    ) -> None:
        """Confirm adding windows."""
        self._store.add_entry(self._user_id, self._windows)
        await self._disable_all(interaction)
        await interaction.edit_original_response(
            content=f"Added {len(self._windows)} free time windows!"
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(
        self, interaction: Interaction, _button: Button[Any]
    ) -> None:
        """Cancel adding windows."""
        await self._disable_all(interaction)
        await interaction.edit_original_response(content="Cancelled.")


class RemoveSelect(View):
    """Select menu for choosing entries to remove."""

    def __init__(
        self, store: ScheduleStore, user_id: int, entries: list[FreeTimeEntry]
    ) -> None:
        """Init."""
        super().__init__(timeout=120)
        self._store = store
        self._user_id = user_id
        options = []
        for e in entries[:25]:
            label = f"{_fmt_short(e.windows[0])} ({len(e.windows)} slots)"
            desc = (
                e.windows[0].start.strftime("%a %Y-%m-%d") if e.windows else ""
            )
            options.append(
                discord.SelectOption(label=label, value=e.id, description=desc)
            )
        if not options:
            options.append(
                discord.SelectOption(label="No entries available", value="none")
            )
        select: Select = Select(
            options=options,
            placeholder="Choose an entry to remove",
            custom_id=f"remove_select_{uuid4().hex}",
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: Interaction) -> None:
        """Handle selection of an entry to remove."""
        item = self.children[0]
        if not isinstance(item, Select):
            return
        if not item.values or item.values[0] == "none":
            return
        modal = RemoveReasonModal(self._store, item.values[0])
        await interaction.response.send_modal(modal)


class RemoveReasonModal(Modal):
    """Optional reason for removing an entry."""

    def __init__(self, store: ScheduleStore, entry_id: str) -> None:
        """Init."""
        super().__init__(title="Remove Free Time")
        self._store = store
        self._entry_id = entry_id
        self._reason: TextInput = TextInput(
            label="Why? (optional)",
            placeholder="Reason for removing this free time",
            required=False,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self._reason)

    async def on_submit(self, interaction: Interaction) -> None:
        """Handle modal submission."""
        reason = self._reason.value or None
        entry = self._store.remove_entry(self._entry_id, reason)
        if entry is None:
            await interaction.response.send_message(
                "Entry not found.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "Removed free time window.", ephemeral=True
        )


class ClearConfirmView(View):
    """Confirm clearing all future entries."""

    def __init__(self, store: ScheduleStore, user_id: int) -> None:
        """Init."""
        super().__init__(timeout=120)
        self._store = store
        self._user_id = user_id

    @discord.ui.button(label="Clear All", style=discord.ButtonStyle.danger)
    async def clear_btn(
        self, interaction: Interaction, _button: Button[Any]
    ) -> None:
        """Open reason modal for clearing."""
        modal = ClearReasonModal(self._store, self._user_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(
        self, interaction: Interaction, _button: Button[Any]
    ) -> None:
        """Cancel clearing."""
        for child in self.children:
            child.disabled = True  # type: ignore[reportAttributeAccessIssue]
        await interaction.response.edit_message(content="Cancelled.", view=self)


class ClearReasonModal(Modal):
    """Optional reason for clearing."""

    def __init__(self, store: ScheduleStore, user_id: int) -> None:
        """Init."""
        super().__init__(title="Clear All Free Time")
        self._store = store
        self._user_id = user_id
        self._reason: TextInput = TextInput(
            label="Why? (optional)",
            placeholder="Reason for clearing all free time",
            required=False,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self._reason)

    async def on_submit(self, interaction: Interaction) -> None:
        """Handle modal submission."""
        reason = self._reason.value or None
        now = datetime.now(UTC)
        removed = self._store.clear_user_entries(self._user_id, now, reason)
        await interaction.response.send_message(
            f"Cleared {len(removed)} future entries.", ephemeral=True
        )


class ModInvitationView(View):
    """Yes/no for mod invitation."""

    def __init__(
        self, event_id: str, target_user_id: int, guild_id: int
    ) -> None:
        """Init."""
        super().__init__(timeout=86400)
        self._event_id = event_id
        self._target_user_id = target_user_id
        self._guild_id = guild_id

    async def _disable_all(self, interaction: Interaction) -> None:
        """Disable all children."""
        for child in self.children:
            child.disabled = True  # type: ignore[reportAttributeAccessIssue]
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(
        self, interaction: Interaction, _button: Button[Any]
    ) -> None:
        """Accept the moderator invitation."""
        if interaction.user.id != self._target_user_id:
            await interaction.response.send_message(
                "Not your invitation.", ephemeral=True
            )
            return
        store = get_event_store(interaction)
        if store is None:
            return
        event = store.get_event(self._event_id)
        if event is None:
            await interaction.response.send_message(
                "Event not found.", ephemeral=True
            )
            return
        new_mods = (*event.moderator_ids, self._target_user_id)
        updated = EventData(
            id=event.id,
            name=event.name,
            creator_id=event.creator_id,
            guild_id=event.guild_id,
            window=event.window,
            participant_ids=event.participant_ids,
            moderator_ids=new_mods,
            participant_thread_id=event.participant_thread_id,
            moderator_thread_id=event.moderator_thread_id,
            is_closed=event.is_closed,
            created_at=event.created_at,
        )
        store.update_event(updated)
        await self._disable_all(interaction)
        await interaction.edit_original_response(
            content="You are now a moderator!"
        )
        if event.moderator_thread_id and interaction.guild:
            mod_thread = interaction.guild.get_thread(event.moderator_thread_id)
            if mod_thread is not None:
                await mod_thread.add_user(interaction.user)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(
        self, interaction: Interaction, _button: Button[Any]
    ) -> None:
        """Decline the moderator invitation."""
        if interaction.user.id != self._target_user_id:
            await interaction.response.send_message(
                "Not your invitation.", ephemeral=True
            )
            return
        await self._disable_all(interaction)
        await interaction.edit_original_response(content="Invitation declined.")


class ModConfirmationView(View):
    """Confirmation view for moderator actions."""

    def __init__(  # noqa: PLR0913
        self,
        event_id: str,
        action: Literal["add_user", "remove_user", "close"],
        reason: str | None,
        target_user_id: int | None,
        moderator_ids: list[int],
        guild_id: int,
    ) -> None:
        """Init."""
        super().__init__(timeout=86400)
        self._event_id = event_id
        self._action: Literal["add_user", "remove_user", "close"] = action
        self._reason = reason
        self._target_user_id = target_user_id
        self._guild_id = guild_id
        deadline = None if action == "close" else _compute_timeout()
        register_pending(
            event_id=event_id,
            action=action,
            reason=reason,
            target_user_id=target_user_id,
            moderator_ids=moderator_ids,
            timeout_at=deadline,
        )

    async def _disable_all(self, interaction: Interaction) -> None:
        """Disable all children."""
        for child in self.children:
            child.disabled = True  # type: ignore[reportAttributeAccessIssue]
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes_btn(
        self, interaction: Interaction, _button: Button[Any]
    ) -> None:
        """Vote yes on the action."""
        mod_id = interaction.user.id
        pending = get_pending(self._event_id, self._action)
        if pending is None:
            await interaction.response.send_message(
                "This confirmation is no longer active.", ephemeral=True
            )
            return
        if mod_id not in pending.votes:
            await interaction.response.send_message(
                "You are not a moderator for this event.", ephemeral=True
            )
            return
        pending.votes[mod_id] = "yes"
        await interaction.response.send_message("Voted yes.", ephemeral=True)
        await self._check_complete(interaction, pending)

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no_btn(
        self, interaction: Interaction, _button: Button[Any]
    ) -> None:
        """Vote no on the action."""
        if self._action == "close":
            await interaction.response.send_message(
                "Close requires all moderators to vote yes. "
                "Use Cancel instead.",
                ephemeral=True,
            )
            return
        mod_id = interaction.user.id
        pending = get_pending(self._event_id, self._action)
        if pending is None:
            await interaction.response.send_message(
                "This confirmation is no longer active.", ephemeral=True
            )
            return
        if mod_id not in pending.votes:
            await interaction.response.send_message(
                "You are not a moderator for this event.", ephemeral=True
            )
            return
        modal = NoReasonModal(self._event_id, self._action, mod_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(
        self, interaction: Interaction, _button: Button[Any]
    ) -> None:
        """Cancel the action entirely."""
        pending = get_pending(self._event_id, self._action)
        if pending is None:
            return
        mod_id = interaction.user.id
        store = get_event_store(interaction)
        ev = store and store.get_event(self._event_id)
        if ev is None or mod_id not in ev.moderator_ids:
            await interaction.response.send_message(
                "Only moderators can cancel.", ephemeral=True
            )
            return
        remove_pending(self._event_id, self._action)
        await self._disable_all(interaction)
        await interaction.edit_original_response(content="Action cancelled.")

    async def _check_complete(
        self, interaction: Interaction, pending: _PendingConfirmation
    ) -> None:
        """Check if all votes are in and handle completion."""
        all_yes = all(v == "yes" for v in pending.votes.values())
        any_no = any(v == "no" for v in pending.votes.values())
        if not all_yes and not any_no:
            return
        remove_pending(self._event_id, self._action)
        store = get_event_store(interaction)
        if store is None:
            return
        event = store.get_event(self._event_id)
        if event is None:
            return
        if any_no:
            await self._handle_rejected(interaction, event, pending)
        else:
            await self._handle_approved(interaction, store, event, pending)

    async def _format_votes(self, pending: _PendingConfirmation) -> str:
        """Format votes for display."""
        lines: list[str] = []
        for mid, vote in pending.votes.items():
            label = vote if vote != "pending" else "no response"
            lines.append(f"<@{mid}>: {label}")
        return "\n".join(lines)

    async def _handle_rejected(
        self,
        interaction: Interaction,
        event: EventData,
        pending: _PendingConfirmation,
    ) -> None:
        """Handle a rejected action."""
        votes_str = await self._format_votes(pending)
        msg = (
            f"Action **{pending.action}** on event **{event.name}** "
            f"was rejected.\n{votes_str}"
        )
        if event.moderator_thread_id and interaction.guild:
            mod_thread = interaction.guild.get_thread(event.moderator_thread_id)
            if mod_thread is not None:
                await mod_thread.send(msg)
        await interaction.followup.send(msg, ephemeral=True)

    async def _handle_approved(
        self,
        interaction: Interaction,
        store: EventStore,
        event: EventData,
        pending: _PendingConfirmation,
    ) -> None:
        """Handle an approved action."""
        target = pending.target_user_id
        if pending.action == "add_user" and target is not None:
            await self._approve_add_user(
                interaction, store, event, target, pending
            )
        elif pending.action == "remove_user" and target is not None:
            await self._approve_remove_user(
                interaction, store, event, target, pending
            )
        elif pending.action == "close":
            await self._approve_close(interaction, store, event)

    async def _approve_add_user(
        self,
        interaction: Interaction,
        store: EventStore,
        event: EventData,
        target: int,
        pending: _PendingConfirmation,  # noqa: ARG002
    ) -> None:
        """Handle approved add-user."""
        new_participants = (*event.participant_ids, target)
        updated = EventData(
            id=event.id,
            name=event.name,
            creator_id=event.creator_id,
            guild_id=event.guild_id,
            window=event.window,
            participant_ids=new_participants,
            moderator_ids=event.moderator_ids,
            participant_thread_id=event.participant_thread_id,
            moderator_thread_id=event.moderator_thread_id,
            is_closed=event.is_closed,
            created_at=event.created_at,
        )
        store.update_event(updated)
        user = interaction.client.get_user(target)
        inv_view = JoinEventView(event.id, target)
        if user is not None:
            with contextlib.suppress(discord.Forbidden):
                await user.send(
                    f"You've been invited to event **{event.name}**!",
                    view=inv_view,
                )
        if event.moderator_thread_id and interaction.guild:
            mod_thread = interaction.guild.get_thread(event.moderator_thread_id)
            if mod_thread is not None:
                await mod_thread.send(
                    f"Approved adding <@{target}>. Invitation sent."
                )
        if event.participant_thread_id and interaction.guild:
            p_thread = interaction.guild.get_thread(event.participant_thread_id)
            if p_thread is not None:
                user_obj = interaction.client.get_user(target)
                if user_obj is not None:
                    await p_thread.add_user(user_obj)

    async def _approve_remove_user(
        self,
        interaction: Interaction,
        store: EventStore,
        event: EventData,
        target: int,
        pending: _PendingConfirmation,
    ) -> None:
        """Handle approved remove-user."""
        new_participants = tuple(
            pid for pid in event.participant_ids if pid != target
        )
        updated = EventData(
            id=event.id,
            name=event.name,
            creator_id=event.creator_id,
            guild_id=event.guild_id,
            window=event.window,
            participant_ids=new_participants,
            moderator_ids=event.moderator_ids,
            participant_thread_id=event.participant_thread_id,
            moderator_thread_id=event.moderator_thread_id,
            is_closed=event.is_closed,
            created_at=event.created_at,
        )
        store.update_event(updated)
        msg = (
            f"You have been removed from event **{event.name}**.\n"
            f"Reason: {pending.reason or 'No reason given.'}"
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        if event.moderator_thread_id and interaction.guild:
            mod_thread = interaction.guild.get_thread(event.moderator_thread_id)
            if mod_thread is not None:
                await mod_thread.send(
                    f"<@{target}> has been removed. Reason: {pending.reason}"
                )
        if event.participant_thread_id and interaction.guild:
            p_thread = interaction.guild.get_thread(event.participant_thread_id)
            if p_thread is not None:
                member = interaction.guild.get_member(target)
                if member is not None:
                    await p_thread.remove_user(member)

    async def _approve_close(
        self, interaction: Interaction, store: EventStore, event: EventData
    ) -> None:
        """Handle approved close."""
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "Event closed.", ephemeral=True
            )
        updated = EventData(
            id=event.id,
            name=event.name,
            creator_id=event.creator_id,
            guild_id=event.guild_id,
            window=event.window,
            participant_ids=event.participant_ids,
            moderator_ids=event.moderator_ids,
            participant_thread_id=event.participant_thread_id,
            moderator_thread_id=event.moderator_thread_id,
            is_closed=True,
            created_at=event.created_at,
        )
        store.update_event(updated)
        if event.participant_thread_id and interaction.guild:
            p_thread = interaction.guild.get_thread(event.participant_thread_id)
            if p_thread is not None:
                await p_thread.edit(archived=True, locked=True)
        if event.moderator_thread_id and interaction.guild:
            m_thread = interaction.guild.get_thread(event.moderator_thread_id)
            if m_thread is not None:
                await m_thread.send("Event has been closed.")


class NoReasonModal(Modal):
    """Reason for voting no."""

    def __init__(
        self,
        event_id: str,
        action: Literal["add_user", "remove_user", "close"],
        mod_id: int,
    ) -> None:
        """Init."""
        super().__init__(title="Reason for No")
        self._event_id = event_id
        self._action: Literal["add_user", "remove_user", "close"] = action
        self._mod_id = mod_id
        self._reason: TextInput = TextInput(
            label="Why not?",
            placeholder="Please provide a reason",
            required=True,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self._reason)

    async def on_submit(self, interaction: Interaction) -> None:
        """Handle modal submission."""
        pending = get_pending(self._event_id, self._action)
        if pending is None:
            await interaction.response.send_message(
                "Confirmation no longer active.", ephemeral=True
            )
            return
        pending.votes[self._mod_id] = "no"
        pending.reason = self._reason.value
        await interaction.response.send_message("Voted no.", ephemeral=True)
        remove_pending(self._event_id, self._action)
        store = get_event_store(interaction)
        if store is None:
            return
        event = store.get_event(self._event_id)
        if event is None:
            return
        votes_str = "\n".join(
            f"<@{mid}>: {vote}" for mid, vote in pending.votes.items()
        )
        msg = (
            f"Action **{pending.action}** on event **{event.name}** "
            f"was rejected.\n{votes_str}"
        )
        if event.moderator_thread_id and interaction.guild:
            mod_thread = interaction.guild.get_thread(event.moderator_thread_id)
            if mod_thread is not None:
                await mod_thread.send(msg)


class JoinEventView(View):
    """Yes/no for joining an event."""

    def __init__(self, event_id: str, target_user_id: int) -> None:
        """Init."""
        super().__init__(timeout=86400)
        self._event_id = event_id
        self._target_user_id = target_user_id

    async def _disable_all(self, interaction: Interaction) -> None:
        """Disable all children."""
        for child in self.children:
            child.disabled = True  # type: ignore[reportAttributeAccessIssue]
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success)
    async def join_btn(
        self, interaction: Interaction, _button: Button[Any]
    ) -> None:
        """Accept the invitation to join."""
        if interaction.user.id != self._target_user_id:
            await interaction.response.send_message(
                "Not your invitation.", ephemeral=True
            )
            return
        modal = JoinReasonModal(self._event_id, self._target_user_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline_btn(
        self, interaction: Interaction, _button: Button[Any]
    ) -> None:
        """Decline the invitation."""
        if interaction.user.id != self._target_user_id:
            await interaction.response.send_message(
                "Not your invitation.", ephemeral=True
            )
            return
        await self._disable_all(interaction)
        await interaction.edit_original_response(content="Invitation declined.")
        store = get_event_store(interaction)
        if store is None:
            return
        event = store.get_event(self._event_id)
        if event and event.moderator_thread_id and interaction.guild:
            mod_thread = interaction.guild.get_thread(event.moderator_thread_id)
            if mod_thread is not None:
                await mod_thread.send(
                    f"<@{self._target_user_id}> declined the invitation."
                )


class JoinReasonModal(Modal):
    """Optional reason for joining an event."""

    def __init__(self, event_id: str, target_user_id: int) -> None:
        """Init."""
        super().__init__(title="Join Event")
        self._event_id = event_id
        self._target_user_id = target_user_id
        self._reason: TextInput = TextInput(
            label="Why joining? (optional)",
            placeholder="You can state why you're joining",
            required=False,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self._reason)

    async def on_submit(self, interaction: Interaction) -> None:
        """Handle modal submission."""
        store = get_event_store(interaction)
        if store is None:
            return
        event = store.get_event(self._event_id)
        if event is None:
            await interaction.response.send_message(
                "Event not found.", ephemeral=True
            )
            return
        new_participants = (*event.participant_ids, self._target_user_id)
        updated = EventData(
            id=event.id,
            name=event.name,
            creator_id=event.creator_id,
            guild_id=event.guild_id,
            window=event.window,
            participant_ids=new_participants,
            moderator_ids=event.moderator_ids,
            participant_thread_id=event.participant_thread_id,
            moderator_thread_id=event.moderator_thread_id,
            is_closed=event.is_closed,
            created_at=event.created_at,
        )
        store.update_event(updated)
        reason_text = (
            f"\nReason: {self._reason.value}" if self._reason.value else ""
        )
        await interaction.response.edit_message(
            content=f"You've joined the event!{reason_text}", view=None
        )
        if event.participant_thread_id and interaction.guild:
            p_thread = interaction.guild.get_thread(event.participant_thread_id)
            if p_thread is not None:
                await p_thread.add_user(interaction.user)
        if event.moderator_thread_id and interaction.guild:
            mod_thread = interaction.guild.get_thread(event.moderator_thread_id)
            if mod_thread is not None:
                await mod_thread.send(
                    f"<@{self._target_user_id}> has joined the event."
                    f"{reason_text}"
                )

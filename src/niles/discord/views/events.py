"""Event management UI components."""
# pyright: reportMissingTypeArgument=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false

import contextlib
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import Literal

import discord
from discord import Interaction
from discord.ui import Button
from discord.ui import Modal
from discord.ui import Select
from discord.ui import TextInput
from discord.ui import View

from niles.discord.models import EventData
from niles.discord.models import PendingConfirmation
from niles.discord.stores import EventStore
from niles.discord.stores import PendingConfirmationStore
from niles.discord.stores import ScheduleStore
from niles.discord.stores import get_event_store
from niles.utils.loggers import LOGGER

_TIMEOUT_MINUTES = 60


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


class EventRoleSelectView(View):
    """Select mod/participant role for event add/remove."""

    def __init__(
        self, action_type: Literal["add", "remove"], target_user: discord.User
    ) -> None:
        """Init."""
        super().__init__(timeout=120)
        self._action_type: Literal["add", "remove", "close"] = action_type
        self._target_user = target_user
        verb = "Add" if action_type == "add" else "Remove"
        options = [
            discord.SelectOption(
                label="Moderator",
                value="mod",
                description=f"{verb} as moderator",
            ),
            discord.SelectOption(
                label="Participant",
                value="user",
                description=f"{verb} as participant",
            ),
        ]
        sel = Select(options=options, placeholder=f"{verb} as...", row=0)
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: Interaction) -> None:
        """Handle role selection, then show event picker."""
        for child in self.children:
            if isinstance(child, Select) and child.values:
                role = child.values[0]
                break
        else:
            return
        view = EventSelectView(
            interaction, self._action_type, self._target_user, role
        )
        await interaction.response.edit_message(
            content="Select an event:", view=view
        )


class EventSelectView(View):
    """Select an event from a dropdown."""

    def __init__(
        self,
        interaction: Interaction,
        action_type: Literal["add", "remove", "close"],
        target_user: discord.User | None,
        role: str | None = None,
    ) -> None:
        """Init."""
        super().__init__(timeout=120)
        self._action_type = action_type
        self._target_user = target_user
        self._role = role

        store = get_event_store(interaction)
        events: list[EventData] = []
        if store is not None:
            events = [e for e in store.get_all_events() if not e.is_closed]

        options = [
            discord.SelectOption(
                label=e.name,
                value=e.id,
                description=e.window.start.strftime("%Y-%m-%d"),
            )
            for e in events[:25]
        ]
        if not options:
            options.append(
                discord.SelectOption(label="No events available", value="none")
            )
        sel = Select(options=options, placeholder="Choose an event", row=0)
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: Interaction) -> None:
        """Handle event selection."""
        for child in self.children:
            if isinstance(child, Select) and child.values:
                event_id = child.values[0]
                break
        else:
            return

        if event_id == "none":
            return

        store = get_event_store(interaction)
        if store is None:
            return
        ev = store.get_event(event_id)
        if ev is None:
            await interaction.response.send_message(
                "Event not found.", ephemeral=True
            )
            return

        if self._action_type == "close":
            await self._proceed_close(interaction, ev)
        elif self._action_type == "remove":
            await self._proceed_remove(interaction, store, ev)
        else:
            await self._proceed_add(interaction, ev)

    async def _proceed_add(
        self, interaction: Interaction, ev: EventData
    ) -> None:
        """Handle add action."""
        target = self._target_user
        if target is None:
            return
        target_id = target.id

        if self._role == "mod":
            if interaction.user.id != ev.creator_id:
                await interaction.response.send_message(
                    "Only the event creator can add moderators.", ephemeral=True
                )
                return
            if target_id in ev.moderator_ids:
                await interaction.response.send_message(
                    "User is already a moderator.", ephemeral=True
                )
                return
            view = ModInvitationView(ev.id, target_id, ev.guild_id)
            with contextlib.suppress(discord.Forbidden):
                await target.send(
                    f"You've been invited to moderate **{ev.name}**!", view=view
                )
            await interaction.response.edit_message(
                content=f"Invitation sent to {target.mention}.", view=None
            )
            LOGGER.info(
                "Mod invitation sent to user {} for event {} by user {}",
                target_id,
                ev.id,
                interaction.user.id,
            )
        else:
            if interaction.user.id not in ev.moderator_ids:
                await interaction.response.send_message(
                    "Only moderators can add users.", ephemeral=True
                )
                return
            if target_id in ev.participant_ids:
                await interaction.response.send_message(
                    "User is already participating.", ephemeral=True
                )
                return
            schedule_store = getattr(interaction.client, "schedules", None)
            if isinstance(schedule_store, ScheduleStore):
                free_ids = schedule_store.get_free_user_ids(ev.window)
                if target_id not in free_ids:
                    await interaction.response.send_message(
                        "Cannot add an occupied user to this event.",
                        ephemeral=True,
                    )
                    return

            mod_ids = list(ev.moderator_ids)
            view = ModConfirmationView(
                event_id=ev.id,
                action="add_user",
                reason=None,
                target_user_id=target_id,
                moderator_ids=mod_ids,
                guild_id=ev.guild_id,
                store=interaction.client.pending_confirmations,  # type: ignore[reportAttributeAccessIssue]
            )
            await interaction.response.edit_message(
                content=(
                    f"Proposal to add {target.mention} "
                    f"to **{ev.name}**.\nModerators, please vote:"
                ),
                view=view,
            )
            LOGGER.info(
                "Add-user proposal for event {} targeting {} "
                "initiated by user {}",
                ev.id,
                target_id,
                interaction.user.id,
            )

    async def _proceed_remove(
        self, interaction: Interaction, store: EventStore, ev: EventData
    ) -> None:
        """Handle remove action."""
        target = self._target_user
        if target is None:
            return
        target_id = target.id

        if self._role == "mod":
            if interaction.user.id != ev.creator_id:
                await interaction.response.send_message(
                    "Only the event creator can remove moderators.",
                    ephemeral=True,
                )
                return
            if target_id not in ev.moderator_ids:
                await interaction.response.send_message(
                    "User is not a moderator.", ephemeral=True
                )
                return
            modal = EventRemoveReasonModal(store, ev, target_id, "mod")
            await interaction.response.send_modal(modal)
        else:
            if interaction.user.id not in ev.moderator_ids:
                await interaction.response.send_message(
                    "Only moderators can remove users.", ephemeral=True
                )
                return
            if target_id not in ev.participant_ids:
                await interaction.response.send_message(
                    "User is not participating.", ephemeral=True
                )
                return
            modal = EventRemoveReasonModal(store, ev, target_id, "user")
            await interaction.response.send_modal(modal)

    async def _proceed_close(
        self, interaction: Interaction, ev: EventData
    ) -> None:
        """Handle accepted request."""
        mod_ids = list(ev.moderator_ids)
        view = ModConfirmationView(
            event_id=ev.id,
            action="close",
            reason=None,
            target_user_id=None,
            moderator_ids=mod_ids,
            guild_id=ev.guild_id,
            store=interaction.client.pending_confirmations,  # type: ignore[reportAttributeAccessIssue]
        )
        await interaction.response.edit_message(
            content=(
                f"Proposal to close **{ev.name}**.\n"
                f"All moderators must approve:"
            ),
            view=view,
        )
        LOGGER.info(
            "Close proposal for event {} initiated by user {}",
            ev.id,
            interaction.user.id,
        )


class EventRemoveReasonModal(Modal):
    """Modal for providing reason when removing from event."""

    def __init__(
        self,
        store: EventStore,
        event: EventData,
        target_user_id: int,
        role: str,
    ) -> None:
        """Init."""
        super().__init__(title=f"Remove {role} from {event.name[:45]}")
        self._store = store
        self._event = event
        self._target_user_id = target_user_id
        self._role = role
        self._reason = TextInput(
            label="Reason",
            placeholder="Why are you removing this user?",
            required=True,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self._reason)

    async def on_submit(self, interaction: Interaction) -> None:
        """Handle modal submission."""
        reason = self._reason.value
        if self._role == "mod":
            new_mods = tuple(
                mid
                for mid in self._event.moderator_ids
                if mid != self._target_user_id
            )
            updated = EventData(
                id=self._event.id,
                name=self._event.name,
                creator_id=self._event.creator_id,
                guild_id=self._event.guild_id,
                window=self._event.window,
                participant_ids=self._event.participant_ids,
                moderator_ids=new_mods,
                participant_thread_id=self._event.participant_thread_id,
                moderator_thread_id=self._event.moderator_thread_id,
                is_closed=self._event.is_closed,
                created_at=self._event.created_at,
            )
            self._store.update_event(updated)
            if self._event.moderator_thread_id and interaction.guild:
                mod_thread = interaction.guild.get_thread(
                    self._event.moderator_thread_id
                )
                if mod_thread is not None:
                    await mod_thread.send(
                        f"<@{self._target_user_id}> has been removed "
                        f"as moderator. Reason: {reason}"
                    )
            LOGGER.info(
                "Moderator {} removed from event {} by user {} (reason={})",
                self._target_user_id,
                self._event.id,
                interaction.user.id,
                reason,
            )
            await interaction.response.send_message(
                f"Removed <@{self._target_user_id}> from moderators.",
                ephemeral=True,
            )
        else:
            mod_ids = list(self._event.moderator_ids)
            view = ModConfirmationView(
                event_id=self._event.id,
                action="remove_user",
                reason=reason,
                target_user_id=self._target_user_id,
                moderator_ids=mod_ids,
                guild_id=self._event.guild_id,
                store=interaction.client.pending_confirmations,  # type: ignore[reportAttributeAccessIssue]
            )
            await interaction.response.send_message(
                f"Proposal to remove <@{self._target_user_id}> "
                f"from **{self._event.name}**.\n"
                f"Reason: {reason}\n"
                f"Moderators, please vote:",
                view=view,
            )
            LOGGER.info(
                "Remove-user proposal for event {} targeting {} "
                "initiated by user {} (reason={})",
                self._event.id,
                self._target_user_id,
                interaction.user.id,
                reason,
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
    async def accept(self, interaction: Interaction, _button: Button) -> None:
        """Accept the moderator invitation."""
        if interaction.user.id != self._target_user_id:
            LOGGER.warning(
                "User {} attempted to accept mod invitation "
                "for event {} meant for {}",
                interaction.user.id,
                self._event_id,
                self._target_user_id,
            )
            await interaction.response.send_message(
                "Not your invitation.", ephemeral=True
            )
            return
        store = get_event_store(interaction)
        if store is None:
            return
        event = store.get_event(self._event_id)
        if event is None:
            LOGGER.warning(
                "Event {} not found in ModInvitationView accept", self._event_id
            )
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
        LOGGER.info(
            "User {} accepted mod invitation for event {}",
            self._target_user_id,
            self._event_id,
        )
        await self._disable_all(interaction)
        await interaction.edit_original_response(
            content="You are now a moderator!"
        )
        if event.moderator_thread_id and interaction.guild:
            mod_thread = interaction.guild.get_thread(event.moderator_thread_id)
            if mod_thread is not None:
                await mod_thread.add_user(interaction.user)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: Interaction, _button: Button) -> None:
        """Decline the moderator invitation."""
        if interaction.user.id != self._target_user_id:
            LOGGER.warning(
                "User {} attempted to decline mod invitation "
                "for event {} meant for {}",
                interaction.user.id,
                self._event_id,
                self._target_user_id,
            )
            await interaction.response.send_message(
                "Not your invitation.", ephemeral=True
            )
            return
        LOGGER.info(
            "User {} declined mod invitation for event {}",
            self._target_user_id,
            self._event_id,
        )
        await self._disable_all(interaction)
        await interaction.edit_original_response(content="Invitation declined.")


class ModConfirmationView(View):
    """Confirmation view for moderator actions."""

    def __init__(  # noqa: PLR0913 — modal params correspond to event data fields
        self,
        event_id: str,
        action: Literal["add_user", "remove_user", "close"],
        reason: str | None,
        target_user_id: int | None,
        moderator_ids: list[int],
        guild_id: int,
        store: PendingConfirmationStore,
    ) -> None:
        """Init."""
        super().__init__(timeout=86400)
        self._event_id = event_id
        self._store = store
        self._action: Literal["add_user", "remove_user", "close"] = action
        self._reason = reason
        self._target_user_id = target_user_id
        self._guild_id = guild_id
        deadline = None if action == "close" else _compute_timeout()
        store.register(
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
    async def yes_btn(self, interaction: Interaction, _button: Button) -> None:
        """Vote yes on the action."""
        mod_id = interaction.user.id
        pending = self._store.get(self._event_id, self._action)
        if pending is None:
            LOGGER.warning(
                "User {} tried to vote yes on inactive {} for event {}",
                mod_id,
                self._action,
                self._event_id,
            )
            await interaction.response.send_message(
                "This confirmation is no longer active.", ephemeral=True
            )
            return
        if mod_id not in pending.votes:
            LOGGER.warning(
                "User {} is not a moderator for event {}, tried yes vote",
                mod_id,
                self._event_id,
            )
            await interaction.response.send_message(
                "You are not a moderator for this event.", ephemeral=True
            )
            return
        pending.votes[mod_id] = "yes"
        LOGGER.info(
            "User {} voted yes on {} for event {}",
            mod_id,
            self._action,
            self._event_id,
        )
        await interaction.response.send_message("Voted yes.", ephemeral=True)
        await self._check_complete(interaction, pending)

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no_btn(self, interaction: Interaction, _button: Button) -> None:
        """Vote no on the action."""
        if self._action == "close":
            LOGGER.warning(
                "User {} tried to vote no on close for event {}",
                interaction.user.id,
                self._event_id,
            )
            await interaction.response.send_message(
                "Close requires all moderators to vote yes. "
                "Use Cancel instead.",
                ephemeral=True,
            )
            return
        mod_id = interaction.user.id
        pending = self._store.get(self._event_id, self._action)
        if pending is None:
            LOGGER.warning(
                "User {} tried to vote no on inactive {} for event {}",
                mod_id,
                self._action,
                self._event_id,
            )
            await interaction.response.send_message(
                "This confirmation is no longer active.", ephemeral=True
            )
            return
        if mod_id not in pending.votes:
            LOGGER.warning(
                "User {} is not a moderator for event {}, tried no vote",
                mod_id,
                self._event_id,
            )
            await interaction.response.send_message(
                "You are not a moderator for this event.", ephemeral=True
            )
            return
        modal = NoReasonModal(self._event_id, self._action, mod_id, self._store)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(
        self, interaction: Interaction, _button: Button
    ) -> None:
        """Cancel the action entirely."""
        pending = self._store.get(self._event_id, self._action)
        if pending is None:
            LOGGER.debug(
                "Cancel pressed but no pending {} for event {}",
                self._action,
                self._event_id,
            )
            return
        mod_id = interaction.user.id
        store = get_event_store(interaction)
        ev = store and store.get_event(self._event_id)
        if ev is None or mod_id not in ev.moderator_ids:
            LOGGER.warning(
                "Non-moderator {} tried to cancel {} for event {}",
                mod_id,
                self._action,
                self._event_id,
            )
            await interaction.response.send_message(
                "Only moderators can cancel.", ephemeral=True
            )
            return
        self._store.remove(self._event_id, self._action)
        LOGGER.info(
            "User {} cancelled {} for event {}",
            mod_id,
            self._action,
            self._event_id,
        )
        await self._disable_all(interaction)
        await interaction.edit_original_response(content="Action cancelled.")

    async def _check_complete(
        self, interaction: Interaction, pending: PendingConfirmation
    ) -> None:
        """Check if all votes are in and handle completion."""
        all_yes = all(v == "yes" for v in pending.votes.values())
        any_no = any(v == "no" for v in pending.votes.values())
        if not all_yes and not any_no:
            return
        self._store.remove(self._event_id, self._action)
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

    async def _format_votes(self, pending: PendingConfirmation) -> str:
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
        pending: PendingConfirmation,
    ) -> None:
        """Handle a rejected action."""
        LOGGER.warning(
            "{} for event {} was rejected (votes={})",
            pending.action,
            event.id,
            dict(pending.votes),
        )
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
        pending: PendingConfirmation,
    ) -> None:
        """Handle an approved action."""
        LOGGER.info("{} for event {} was approved", pending.action, event.id)
        target = pending.target_user_id
        if pending.action == "add_user" and target is not None:
            await self._approve_add_user(interaction, store, event, target)
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
        pending: PendingConfirmation,
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
        store: PendingConfirmationStore,
    ) -> None:
        """Init."""
        super().__init__(title="Reason for No")
        self._event_id = event_id
        self._action: Literal["add_user", "remove_user", "close"] = action
        self._mod_id = mod_id
        self._store = store
        self._reason: TextInput = TextInput(
            label="Why not?",
            placeholder="Please provide a reason",
            required=True,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self._reason)

    async def on_submit(self, interaction: Interaction) -> None:
        """Handle modal submission."""
        pending = self._store.get(self._event_id, self._action)
        if pending is None:
            LOGGER.warning(
                "NoReasonModal: no pending {} for event {}",
                self._action,
                self._event_id,
            )
            await interaction.response.send_message(
                "Confirmation no longer active.", ephemeral=True
            )
            return
        pending.votes[self._mod_id] = "no"
        pending.reason = self._reason.value
        LOGGER.info(
            "User {} voted no on {} for event {} (reason={})",
            self._mod_id,
            self._action,
            self._event_id,
            self._reason.value,
        )
        await interaction.response.send_message("Voted no.", ephemeral=True)
        self._store.remove(self._event_id, self._action)
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
    async def join_btn(self, interaction: Interaction, _button: Button) -> None:
        """Accept the invitation to join."""
        if interaction.user.id != self._target_user_id:
            LOGGER.warning(
                "User {} attempted to join event {} as {}",
                interaction.user.id,
                self._event_id,
                self._target_user_id,
            )
            await interaction.response.send_message(
                "Not your invitation.", ephemeral=True
            )
            return
        LOGGER.info(
            "User {} accepted invitation to join event {}",
            self._target_user_id,
            self._event_id,
        )
        modal = JoinReasonModal(self._event_id, self._target_user_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline_btn(
        self, interaction: Interaction, _button: Button
    ) -> None:
        """Decline the invitation."""
        if interaction.user.id != self._target_user_id:
            LOGGER.warning(
                "User {} attempted to decline invitation for event {} as {}",
                interaction.user.id,
                self._event_id,
                self._target_user_id,
            )
            await interaction.response.send_message(
                "Not your invitation.", ephemeral=True
            )
            return
        LOGGER.info(
            "User {} declined invitation to event {}",
            self._target_user_id,
            self._event_id,
        )
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
            LOGGER.error(
                "EventStore unavailable in JoinReasonModal for event {}",
                self._event_id,
            )
            return
        event = store.get_event(self._event_id)
        if event is None:
            LOGGER.warning(
                "Event {} not found in JoinReasonModal", self._event_id
            )
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
        LOGGER.info(
            "User {} joined event {} (reason={})",
            self._target_user_id,
            self._event_id,
            self._reason.value or None,
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

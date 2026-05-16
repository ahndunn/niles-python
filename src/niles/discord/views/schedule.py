"""Schedule (free time) UI components."""
# pyright: reportMissingTypeArgument=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false

from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import TYPE_CHECKING
from uuid import uuid4

import discord
from discord import Interaction
from discord.ui import Button
from discord.ui import Modal
from discord.ui import Select
from discord.ui import TextInput
from discord.ui import View

from niles.discord.models import FreeTimeEntry
from niles.discord.models import TimeWindow
from niles.utils.loggers import LOGGER

if TYPE_CHECKING:
    from niles.discord.stores import ScheduleStore

_PREVIEW_LIMIT = 20


def _fmt_range(w: TimeWindow, offset: timedelta = timedelta(0)) -> str:
    """Format a time window as a readable range."""
    user_tz = timezone(offset)
    local_start = w.start.astimezone(user_tz)
    local_end = w.end.astimezone(user_tz)
    return (
        f"{local_start.strftime('%a %Y-%m-%d %H:%M')}"
        f"-{local_end.strftime('%H:%M')}"
    )


def _fmt_short(w: TimeWindow, offset: timedelta = timedelta(0)) -> str:
    """Format a time window as short time range."""
    user_tz = timezone(offset)
    local_start = w.start.astimezone(user_tz)
    local_end = w.end.astimezone(user_tz)
    return f"{local_start.strftime('%H:%M')}-{local_end.strftime('%H:%M')}"


def _merge_windows(windows: list[TimeWindow]) -> list[TimeWindow]:
    """Merge consecutive time windows into larger ranges."""
    if not windows:
        return []
    sorted_windows = sorted(windows, key=lambda w: w.start)
    merged = [sorted_windows[0]]
    for w in sorted_windows[1:]:
        if w.start == merged[-1].end:
            merged[-1] = TimeWindow(start=merged[-1].start, end=w.end)
        else:
            merged.append(w)
    return merged


class ScheduleDateRangeModal(Modal):
    """Modal for picking a date range with year/month/day boxes."""

    def __init__(
        self, store: ScheduleStore, user_id: int, offset: timedelta
    ) -> None:
        """Init."""
        super().__init__(title="Add Free Time - Select Dates")
        self._store = store
        self._user_id = user_id
        self._offset = offset

        now = datetime.now(UTC).astimezone(timezone(offset))

        self._start_year = TextInput(
            label="Start Year",
            placeholder="2024",
            default=str(now.year),
            required=True,
            min_length=4,
            max_length=4,
        )
        self._start_month = TextInput(
            label="Start Month",
            placeholder="1-12",
            default=str(now.month),
            required=True,
            min_length=1,
            max_length=2,
        )
        self._start_day = TextInput(
            label="Start Day",
            placeholder="1-31",
            default=str(now.day),
            required=True,
            min_length=1,
            max_length=2,
        )
        week_later = now + timedelta(days=7)
        self._end_year = TextInput(
            label="End Year",
            placeholder="2024",
            default=str(week_later.year),
            required=True,
            min_length=4,
            max_length=4,
        )
        self._end_month = TextInput(
            label="End Month",
            placeholder="1-12",
            default=str(week_later.month),
            required=True,
            min_length=1,
            max_length=2,
        )
        self._end_day = TextInput(
            label="End Day",
            placeholder="1-31",
            default=str(week_later.day),
            required=True,
            min_length=1,
            max_length=2,
        )

        self.add_item(self._start_year)
        self.add_item(self._start_month)
        self.add_item(self._start_day)
        self.add_item(self._end_year)
        self.add_item(self._end_month)
        self.add_item(self._end_day)

    async def on_submit(self, interaction: Interaction) -> None:
        """Handle modal submission."""
        try:
            sy = int(self._start_year.value)
            sm = int(self._start_month.value)
            sd = int(self._start_day.value)
            ey = int(self._end_year.value)
            em = int(self._end_month.value)
            ed_ = int(self._end_day.value)
        except ValueError:
            await interaction.response.send_message(
                "Invalid date values. Enter numbers.", ephemeral=True
            )
            return

        try:
            start = date(sy, sm, sd)
            end = date(ey, em, ed_)
        except ValueError:
            await interaction.response.send_message(
                "Invalid date. Check year/month/day.", ephemeral=True
            )
            return

        if start > end:
            await interaction.response.send_message(
                "Start date must be before end date.", ephemeral=True
            )
            return

        dates: list[date] = []
        current = start
        while current <= end:
            dates.append(current)
            current += timedelta(days=1)

        configs: dict[int, tuple[str, str]] = {}
        view = ScheduleDateConfigView(
            self._store, self._user_id, self._offset, dates, configs
        )
        await interaction.response.send_message(
            f"Configure time ranges for each date ({len(dates)} dates).",
            view=view,
            ephemeral=True,
        )


class ScheduleDateConfigView(View):
    """Interactive view for per-date time configuration."""

    def __init__(
        self,
        store: ScheduleStore,
        user_id: int,
        offset: timedelta,
        dates: list[date],
        configs: dict[int, tuple[str, str]],
    ) -> None:
        """Init."""
        super().__init__(timeout=300)
        self._store = store
        self._user_id = user_id
        self._offset = offset
        self._dates = dates
        self._configs = configs

        unconfigured = [(i, d) for i, d in enumerate(dates) if i not in configs]
        if unconfigured:
            options = [
                discord.SelectOption(
                    label=d.strftime("%a %Y-%m-%d"), value=str(i)
                )
                for i, d in unconfigured[:25]
            ]
            sel = Select(
                options=options,
                placeholder="Pick a date to configure...",
                row=0,
            )
            sel.callback = self._on_select_date
            self.add_item(sel)

        if configs:
            confirm = Button(
                label="Confirm & Save", style=discord.ButtonStyle.success, row=1
            )
            confirm.callback = self._on_confirm
            self.add_item(confirm)

    async def _on_select_date(self, interaction: Interaction) -> None:
        """Open a modal to set time for the selected date."""
        for child in self.children:
            if isinstance(child, Select) and child.values:
                idx = int(child.values[0])
                break
        else:
            return
        date_ = self._dates[idx]
        existing = self._configs.get(idx)
        modal = ScheduleDateModal(
            date_,
            existing,
            self._configs,
            idx,
            self._offset,
            self._store,
            self._user_id,
            self._dates,
        )
        await interaction.response.send_modal(modal)

    async def _on_confirm(self, interaction: Interaction) -> None:
        """Generate windows from per-date configs and show preview."""
        windows: list[TimeWindow] = []
        user_tz = timezone(self._offset)
        for idx, (st, et) in self._configs.items():
            d = self._dates[idx]
            try:
                sh, smi = (int(x) for x in st.split(":"))
                eh, emi = (int(x) for x in et.split(":"))
            except ValueError:
                continue
            win_start = datetime(
                d.year, d.month, d.day, sh, smi, tzinfo=user_tz
            ).astimezone(UTC)
            win_end = datetime(
                d.year, d.month, d.day, eh, emi, tzinfo=user_tz
            ).astimezone(UTC)
            while win_start + timedelta(minutes=15) <= win_end:
                w_end = win_start + timedelta(minutes=15)
                windows.append(TimeWindow(start=win_start, end=w_end))
                win_start = w_end

        if not windows:
            await interaction.response.send_message(
                "No windows generated. Check your time ranges.", ephemeral=True
            )
            return

        windows = _merge_windows(windows)
        windows_t = tuple(windows)

        preview_items = windows_t[:_PREVIEW_LIMIT]
        preview = "\n".join(_fmt_range(w, self._offset) for w in preview_items)
        if len(windows_t) > _PREVIEW_LIMIT:
            preview += f"\n... and {len(windows_t) - _PREVIEW_LIMIT} more"

        view = ConfirmWindowsView(self._store, self._user_id, windows_t)
        msg = (
            f"Generated {len(windows_t)} windows:\n"
            f"```\n{preview}\n```\nConfirm?"
        )
        await interaction.response.send_message(msg, view=view, ephemeral=True)


class ScheduleDateModal(Modal):
    """Modal for setting time range for a specific date."""

    def __init__(  # noqa: PLR0913 — modal requires date context and store refs
        self,
        date_: date,
        existing: tuple[str, str] | None,
        configs: dict[int, tuple[str, str]],
        date_idx: int,
        offset: timedelta,
        store: ScheduleStore,
        user_id: int,
        dates: list[date],
    ) -> None:
        """Init."""
        super().__init__(title=f"Time for {date_.strftime('%a %Y-%m-%d')}")
        self._date = date_
        self._configs = configs
        self._date_idx = date_idx
        self._offset = offset
        self._store = store
        self._user_id = user_id
        self._dates = dates

        default_start = existing[0] if existing else "09:00"
        default_end = existing[1] if existing else "17:00"

        self._start_time = TextInput(
            label="Start Time",
            placeholder="HH:MM (24h)",
            default=default_start,
            required=True,
            min_length=5,
            max_length=5,
        )
        self._end_time = TextInput(
            label="End Time",
            placeholder="HH:MM (24h)",
            default=default_end,
            required=True,
            min_length=5,
            max_length=5,
        )
        self.add_item(self._start_time)
        self.add_item(self._end_time)

    async def on_submit(self, interaction: Interaction) -> None:
        """Handle modal submission."""
        st = self._start_time.value
        et = self._end_time.value
        try:
            sh, smi = (int(x) for x in st.split(":"))
            eh, emi = (int(x) for x in et.split(":"))
        except ValueError:
            await interaction.response.send_message(
                "Invalid time format. Use HH:MM.", ephemeral=True
            )
            return

        if eh < sh or (eh == sh and emi <= smi):
            await interaction.response.send_message(
                "End time must be after start time.", ephemeral=True
            )
            return

        self._configs[self._date_idx] = (st, et)
        new_view = ScheduleDateConfigView(
            self._store, self._user_id, self._offset, self._dates, self._configs
        )
        await interaction.response.send_message(
            f"Time set for {self._date.strftime('%a %Y-%m-%d')}: {st}-{et}",
            view=new_view,
            ephemeral=True,
        )


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
    async def confirm(self, interaction: Interaction, _button: Button) -> None:
        """Confirm adding windows."""
        self._store.add_entry(self._user_id, self._windows)
        LOGGER.info(
            "User {} confirmed and added {} free time windows",
            interaction.user.id,
            len(self._windows),
        )
        await self._disable_all(interaction)
        await interaction.edit_original_response(
            content=f"Added {len(self._windows)} free time windows!"
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: Interaction, _button: Button) -> None:
        """Cancel adding windows."""
        LOGGER.info(
            "User {} cancelled adding {} free time windows",
            interaction.user.id,
            len(self._windows),
        )
        await self._disable_all(interaction)
        await interaction.edit_original_response(content="Cancelled.")


class RemoveSelect(View):
    """Select menu for choosing entries to remove."""

    def __init__(
        self,
        store: ScheduleStore,
        user_id: int,
        entries: list[FreeTimeEntry],
        offset: timedelta = timedelta(0),
    ) -> None:
        """Init."""
        super().__init__(timeout=120)
        self._store = store
        self._user_id = user_id
        self._offset = offset
        options = []
        for e in entries[:25]:
            label = (
                f"{_fmt_short(e.windows[0], offset)} ({len(e.windows)} slots)"
            )
            user_tz = timezone(offset)
            desc = (
                e.windows[0].start.astimezone(user_tz).strftime("%a %Y-%m-%d")
                if e.windows
                else ""
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
        LOGGER.debug(
            "User {} selected entry {} for removal",
            interaction.user.id,
            item.values[0],
        )
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
            LOGGER.warning(
                "Remove failed: entry {} not found for user {}",
                self._entry_id,
                interaction.user.id,
            )
            await interaction.response.send_message(
                "Entry not found.", ephemeral=True
            )
            return
        LOGGER.info(
            "User {} removed entry {} (reason={})",
            interaction.user.id,
            self._entry_id,
            reason,
        )
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
        self, interaction: Interaction, _button: Button
    ) -> None:
        """Open reason modal for clearing."""
        LOGGER.info("User {} initiated clear all entries", interaction.user.id)
        modal = ClearReasonModal(self._store, self._user_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(
        self, interaction: Interaction, _button: Button
    ) -> None:
        """Cancel clearing."""
        LOGGER.info("User {} cancelled clearing entries", interaction.user.id)
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
        LOGGER.info(
            "User {} cleared {} entries (reason={})",
            interaction.user.id,
            len(removed),
            reason,
        )
        await interaction.response.send_message(
            f"Cleared {len(removed)} future entries.", ephemeral=True
        )

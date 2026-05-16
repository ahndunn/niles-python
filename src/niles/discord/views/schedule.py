"""Schedule (free time) UI components."""
# pyright: reportMissingTypeArgument=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false

import calendar
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
from discord.ui import Select
from discord.ui import View

from niles.discord.models import FreeTimeEntry
from niles.discord.models import TimeWindow
from niles.utils.loggers import LOGGER

if TYPE_CHECKING:
    from niles.discord.stores import ScheduleStore


def _first_val(interaction: Interaction) -> str | None:
    """Extract the first selected value from a Select interaction."""
    for child in interaction.data.get("components", []):  # type: ignore[reportAttributeAccessIssue]
        for comp in child.get("components", []):
            vals = comp.get("values", [])
            if vals:
                return vals[0]
    return None


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


class ScheduleDateRangeView(View):
    """Entry point: start date range selection flow."""

    def __init__(  # noqa: D107
        self, store: ScheduleStore, user_id: int, offset: timedelta
    ) -> None:
        super().__init__(timeout=300)
        self._store = store
        self._user_id = user_id
        self._offset = offset
        now = datetime.now(UTC).astimezone(timezone(offset))
        sel = Select(
            options=[
                discord.SelectOption(label=str(y), value=str(y))
                for y in range(now.year, now.year + 5)
            ],
            placeholder="Select start year",
            row=0,
        )

        async def on_year(interaction: Interaction) -> None:
            val = _first_val(interaction)
            if val is None:
                return
            nv = _ScheduleDatePickView(
                self._store, self._user_id, self._offset, 2, start_year=int(val)
            )
            await interaction.response.edit_message(
                content=f"Start year: **{val}**. Select start month:", view=nv
            )

        sel.callback = on_year
        self.add_item(sel)


class _ScheduleDatePickView(View):
    """Recursive step view for building a start/end date range."""

    def __init__(  # noqa: PLR0913
        self,
        store: ScheduleStore,
        user_id: int,
        offset: timedelta,
        step: int,  # 1=start_year, 2=start_month, 3=start_day, 4=end_year, 5=end_month, 6=end_day  # noqa: E501
        start_year: int = 0,
        start_month: int = 0,
        start_day: int = 0,
        end_year: int = 0,
        end_month: int = 0,
    ) -> None:
        super().__init__(timeout=300)
        self._store = store
        self._user_id = user_id
        self._offset = offset
        self._step = step
        self._sy = start_year
        self._sm = start_month
        self._sd = start_day
        self._ey = end_year
        self._em = end_month
        self._make_select()

    def _make_select(self) -> None:
        now = datetime.now(UTC).astimezone(timezone(self._offset))

        if self._step == 1:
            title = "Start Year"
            current = now.year
            opts = [
                discord.SelectOption(label=str(y), value=str(y))
                for y in range(current, current + 5)
            ]
        elif self._step == 2:  # noqa: PLR2004
            title = "Start Month"
            opts = [
                discord.SelectOption(label=str(m), value=str(m))
                for m in range(1, 13)
            ]
        elif self._step == 3:  # noqa: PLR2004
            title = "Start Day"
            max_d = calendar.monthrange(self._sy, self._sm)[1]
            opts = [
                discord.SelectOption(label=str(d), value=str(d))
                for d in range(1, max_d + 1)
            ]
        elif self._step == 4:  # noqa: PLR2004
            title = "End Year"
            opts = [
                discord.SelectOption(label=str(y), value=str(y))
                for y in range(self._sy, self._sy + 5)
            ]
        elif self._step == 5:  # noqa: PLR2004
            title = "End Month"
            opts = [
                discord.SelectOption(label=str(m), value=str(m))
                for m in range(1, 13)
            ]
        else:
            title = "End Day"
            max_d = calendar.monthrange(self._ey, self._em)[1]
            opts = [
                discord.SelectOption(label=str(d), value=str(d))
                for d in range(1, max_d + 1)
            ]

        sel = Select(options=opts, placeholder=f"Select {title}", row=0)
        sel.callback = self._on_pick
        self.add_item(sel)

    async def _on_pick(self, interaction: Interaction) -> None:
        val = _first_val(interaction)
        if val is None:
            return

        if self._step == 1:
            nv = _ScheduleDatePickView(
                self._store, self._user_id, self._offset, 2, start_year=int(val)
            )
            await interaction.response.edit_message(
                content=f"Start year: **{val}**. Select start month:", view=nv
            )
        elif self._step == 2:  # noqa: PLR2004
            nv = _ScheduleDatePickView(
                self._store,
                self._user_id,
                self._offset,
                3,
                start_year=self._sy,
                start_month=int(val),
            )
            await interaction.response.edit_message(
                content=f"Start month: **{val}**. Select start day:", view=nv
            )
        elif self._step == 3:  # noqa: PLR2004
            nv = _ScheduleDatePickView(
                self._store,
                self._user_id,
                self._offset,
                4,
                start_year=self._sy,
                start_month=self._sm,
                start_day=int(val),
            )
            await interaction.response.edit_message(
                content=(
                    f"Start date: **{self._sy}-{self._sm:02d}-{int(val):02d}**."
                    " Select end year:"
                ),
                view=nv,
            )
        elif self._step == 4:  # noqa: PLR2004
            nv = _ScheduleDatePickView(
                self._store,
                self._user_id,
                self._offset,
                5,
                start_year=self._sy,
                start_month=self._sm,
                start_day=self._sd,
                end_year=int(val),
            )
            await interaction.response.edit_message(
                content=f"End year: **{val}**. Select end month:", view=nv
            )
        elif self._step == 5:  # noqa: PLR2004
            nv = _ScheduleDatePickView(
                self._store,
                self._user_id,
                self._offset,
                6,
                start_year=self._sy,
                start_month=self._sm,
                start_day=self._sd,
                end_year=self._ey,
                end_month=int(val),
            )
            await interaction.response.edit_message(
                content=f"End month: **{val}**. Select end day:", view=nv
            )
        else:
            end_day = int(val)
            try:
                start = date(self._sy, self._sm, self._sd)
                end = date(self._ey, self._em, end_day)
            except ValueError:
                await interaction.response.edit_message(
                    content="Invalid date. Use `/schedule add` to start over.",
                    view=None,
                )
                return
            if start > end:
                await interaction.response.edit_message(
                    content="Start date must be before end date. Use `/schedule add` to start over.",  # noqa: E501
                    view=None,
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
            content = (
                f"Date range: **{start}** to **{end}** ({len(dates)} days).\n"
                f"Set time ranges for each date by selecting it below, "
                f"then click **Confirm & Save** when done."
            )
            LOGGER.debug(
                "User {} selected date range {} to {} ({} days)",
                self._user_id,
                start,
                end,
                len(dates),
            )
            await interaction.response.edit_message(content=content, view=view)


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
        """Open a time select view for the selected date."""
        for child in self.children:
            if isinstance(child, Select) and child.values:
                idx = int(child.values[0])
                break
        else:
            return
        date_ = self._dates[idx]
        existing = self._configs.get(idx)
        await interaction.response.edit_message(
            content=f"Set time for **{date_.strftime('%a %Y-%m-%d')}**:",
            view=ScheduleTimeSelectView(
                self._store,
                self._user_id,
                self._offset,
                self._dates,
                self._configs,
                idx,
                date_,
                existing,
            ),
        )

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


class ScheduleTimeSelectView(View):
    """Select start/end times for a specific date via hour/minute selects."""

    def __init__(  # noqa: D107, PLR0913
        self,
        store: ScheduleStore,
        user_id: int,
        offset: timedelta,
        dates: list[date],
        configs: dict[int, tuple[str, str]],
        date_idx: int,
        date_: date,
        existing: tuple[str, str] | None,
    ) -> None:
        super().__init__(timeout=300)
        self._store = store
        self._user_id = user_id
        self._offset = offset
        self._dates = dates
        self._configs = configs
        self._date_idx = date_idx
        self._date = date_
        self._start_h: int | None = None
        self._start_m: int | None = None
        self._end_h: int | None = None
        self._end_m: int | None = None

        default_s = existing[0] if existing else "09:00"
        default_e = existing[1] if existing else "17:00"
        ds_h, ds_m = (int(x) for x in default_s.split(":"))
        de_h, de_m = (int(x) for x in default_e.split(":"))

        hour_opts = [
            discord.SelectOption(label=f"{h:02d}", value=str(h))
            for h in range(24)
        ]
        min_opts = [
            discord.SelectOption(label=f"{m:02d}", value=str(m))
            for m in (0, 15, 30, 45)
        ]

        self._sh_sel = Select(
            options=hour_opts, placeholder="Start hour", row=0
        )
        self._sh_sel.callback = self._on_sh
        if existing:
            self._sh_sel.options = [
                o
                if o.value != str(ds_h)
                else discord.SelectOption(
                    label=o.label, value=o.value, default=True
                )
                for o in self._sh_sel.options
            ]
        self.add_item(self._sh_sel)

        self._sm_sel = Select(
            options=min_opts, placeholder="Start minute", row=1
        )
        self._sm_sel.callback = self._on_sm
        if existing:
            self._sm_sel.options = [
                o
                if o.value != str(ds_m)
                else discord.SelectOption(
                    label=o.label, value=o.value, default=True
                )
                for o in self._sm_sel.options
            ]
        self.add_item(self._sm_sel)

        self._eh_sel = Select(options=hour_opts, placeholder="End hour", row=2)
        self._eh_sel.callback = self._on_eh
        if existing:
            self._eh_sel.options = [
                o
                if o.value != str(de_h)
                else discord.SelectOption(
                    label=o.label, value=o.value, default=True
                )
                for o in self._eh_sel.options
            ]
        self.add_item(self._eh_sel)

        self._em_sel = Select(options=min_opts, placeholder="End minute", row=3)
        self._em_sel.callback = self._on_em
        if existing:
            self._em_sel.options = [
                o
                if o.value != str(de_m)
                else discord.SelectOption(
                    label=o.label, value=o.value, default=True
                )
                for o in self._em_sel.options
            ]
        self.add_item(self._em_sel)

    async def _on_sh(self, interaction: Interaction) -> None:
        self._start_h = int(self._sh_sel.values[0])
        await self._maybe_save(interaction)

    async def _on_sm(self, interaction: Interaction) -> None:
        self._start_m = int(self._sm_sel.values[0])
        await self._maybe_save(interaction)

    async def _on_eh(self, interaction: Interaction) -> None:
        self._end_h = int(self._eh_sel.values[0])
        await self._maybe_save(interaction)

    async def _on_em(self, interaction: Interaction) -> None:
        self._end_m = int(self._em_sel.values[0])
        await self._maybe_save(interaction)

    async def _maybe_save(self, interaction: Interaction) -> None:
        sh = self._start_h
        sm = self._start_m
        eh = self._end_h
        em = self._end_m
        if sh is None or sm is None or eh is None or em is None:
            await interaction.response.defer()
            return

        st = f"{sh:02d}:{sm:02d}"
        et = f"{eh:02d}:{em:02d}"

        if eh < sh or (eh == sh and em <= sm):
            await interaction.response.edit_message(
                content=f"End time must be after start time. Set time for **{self._date.strftime('%a %Y-%m-%d')}**:",  # noqa: E501
                view=ScheduleTimeSelectView(
                    self._store,
                    self._user_id,
                    self._offset,
                    self._dates,
                    self._configs,
                    self._date_idx,
                    self._date,
                    (st, et),
                ),
            )
            return

        self._configs[self._date_idx] = (st, et)
        new_view = ScheduleDateConfigView(
            self._store, self._user_id, self._offset, self._dates, self._configs
        )
        await interaction.response.edit_message(
            content=f"Time set for **{self._date.strftime('%a %Y-%m-%d')}**: {st} – {et}",  # noqa: E501, RUF001
            view=new_view,
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
        view = RemoveReasonView(self._store, item.values[0])
        await interaction.response.edit_message(
            content="Remove this free time window? Select a reason or skip:",
            view=view,
        )


class RemoveReasonView(View):
    """Optional reason for removing an entry via select."""

    def __init__(self, store: ScheduleStore, entry_id: str) -> None:  # noqa: D107
        super().__init__(timeout=120)
        self._store = store
        self._entry_id = entry_id
        reasons = [
            discord.SelectOption(label="No reason needed", value="__none__"),
            discord.SelectOption(
                label="Schedule changed", value="schedule changed"
            ),
            discord.SelectOption(
                label="No longer free", value="no longer free"
            ),
            discord.SelectOption(label="Wrong entry", value="wrong entry"),
            discord.SelectOption(
                label="Other (type reason)", value="__other__"
            ),
        ]
        sel = Select(
            options=reasons, placeholder="Select reason (or skip)", row=0
        )
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: Interaction) -> None:
        val = _first_val(interaction)
        if val is None:
            return
        if val == "__other__":
            await interaction.response.edit_message(
                content="Type your reason below:", view=None
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
                await interaction.followup.send("Timed out.", ephemeral=True)
                return

            reason = msg.content.strip() or None
            await interaction.followup.send(f"Reason: {reason}", ephemeral=True)
        else:
            reason = None if val == "__none__" else val
            await interaction.response.edit_message(
                content=f"Reason: {reason or 'None'}", view=None
            )
        await self._do_remove(interaction, reason)

    async def _do_remove(
        self, interaction: Interaction, reason: str | None
    ) -> None:
        entry = self._store.remove_entry(self._entry_id, reason)
        if entry is None:
            LOGGER.warning(
                "Remove failed: entry {} not found for user {}",
                self._entry_id,
                interaction.user.id,
            )
            await interaction.followup.send("Entry not found.", ephemeral=True)
            return
        LOGGER.info(
            "User {} removed entry {} (reason={})",
            interaction.user.id,
            self._entry_id,
            reason,
        )
        await interaction.followup.send(
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
        """Show reason select for clearing."""
        LOGGER.info("User {} initiated clear all entries", interaction.user.id)
        view = ClearReasonView(self._store, self._user_id)
        await interaction.response.edit_message(
            content="Clear all future entries? Select a reason or skip:",
            view=view,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(
        self, interaction: Interaction, _button: Button
    ) -> None:
        """Cancel clearing."""
        LOGGER.info("User {} cancelled clearing entries", interaction.user.id)
        for child in self.children:
            child.disabled = True  # type: ignore[reportAttributeAccessIssue]
        await interaction.response.edit_message(content="Cancelled.", view=self)


class ClearReasonView(View):
    """Optional reason for clearing via select."""

    def __init__(self, store: ScheduleStore, user_id: int) -> None:  # noqa: D107
        super().__init__(timeout=120)
        self._store = store
        self._user_id = user_id
        reasons = [
            discord.SelectOption(label="No reason needed", value="__none__"),
            discord.SelectOption(
                label="Schedule changed", value="schedule changed"
            ),
            discord.SelectOption(
                label="Not needed anymore", value="not needed anymore"
            ),
            discord.SelectOption(
                label="Other (type reason)", value="__other__"
            ),
        ]
        sel = Select(
            options=reasons, placeholder="Select reason (or skip)", row=0
        )
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: Interaction) -> None:
        val = _first_val(interaction)
        if val is None:
            return
        if val == "__other__":
            await interaction.response.edit_message(
                content="Type your reason below:", view=None
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
                await interaction.followup.send("Timed out.", ephemeral=True)
                return

            reason = msg.content.strip() or None
            await interaction.followup.send(f"Reason: {reason}", ephemeral=True)
        else:
            reason = None if val == "__none__" else val
            await interaction.response.edit_message(
                content=f"Reason: {reason or 'None'}", view=None
            )
        await self._do_clear(interaction, reason)

    async def _do_clear(
        self, interaction: Interaction, reason: str | None
    ) -> None:
        now = datetime.now(UTC)
        removed = self._store.clear_user_entries(self._user_id, now, reason)
        LOGGER.info(
            "User {} cleared {} entries (reason={})",
            interaction.user.id,
            len(removed),
            reason,
        )
        await interaction.followup.send(
            f"Cleared {len(removed)} future entries.", ephemeral=True
        )

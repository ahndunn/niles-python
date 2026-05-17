"""Schedule (free time) UI components."""

import calendar
from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import TYPE_CHECKING
from typing import Any
from typing import cast
from uuid import uuid4

import discord
from discord import Interaction
from discord.ui import Button
from discord.ui import Select

from niles.discord.models import FreeTimeEntry
from niles.discord.models import TimeWindow
from niles.discord.views.base import NilesView
from niles.utils.loggers import LOGGER

if TYPE_CHECKING:
    from niles.discord.databases.schedule import ScheduleStore


def _first_val(interaction: Interaction) -> str | None:
    """Extract the first selected value from a Select interaction."""
    data = cast("dict[str, Any]", interaction.data)
    vals = data.get("values")
    if vals:
        return vals[0]
    for child in data.get("components", []):
        comps = cast("list[dict[str, Any]]", child.get("components", []))
        for comp in comps:
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


def _chunk[T](items: list[T], size: int) -> list[list[T]]:
    """Split a list into chunks of the given size."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def _build_config_summary(ctx: _ScheduleEditContext) -> str:
    """Build a summary of all configured dates/times."""
    if not ctx.configs:
        return "**Your Free Time Selections:**\n*None yet*"
    lines = ["**Your Free Time Selections:**"]
    for i, d in enumerate(ctx.dates):
        windows = ctx.configs.get(i)
        if windows:
            windows_str = ", ".join(f"{st}-{et}" for st, et in windows)
            lines.append(f"📅 {d.strftime('%a %Y-%m-%d')}: {windows_str}")
    return "\n".join(lines)


def _fmt_windows(windows: list[tuple[str, str]]) -> str:
    """Format a list of time windows as a string."""
    if not windows:
        return "None"
    return ", ".join(f"{st}-{et}" for st, et in windows)


@dataclass(frozen=True, slots=True)
class _DateRangeState:
    """Accumulated state for date range selection wizard."""

    sy: int = 0
    sm: int = 0
    sd: int = 0
    ey: int = 0
    em: int = 0


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


class ScheduleDateRangeView(NilesView):
    """Entry point: start date range selection flow."""

    def __init__(  # noqa: D107
        self, store: ScheduleStore, user_id: int, offset: timedelta
    ) -> None:
        super().__init__(timeout=300)
        self._store = store
        self._user_id = user_id
        self._offset = offset
        now = datetime.now(UTC).astimezone(timezone(offset))
        sel: Select[Any] = Select(
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
                self._store,
                self._user_id,
                self._offset,
                2,
                _DateRangeState(sy=int(val)),
            )
            await interaction.response.edit_message(
                content=f"Start year: **{val}**. Select start month:", view=nv
            )

        sel.callback = on_year
        self.add_item(sel)


class _ScheduleDatePickView(NilesView):
    """Recursive step view for building a start/end date range."""

    def __init__(
        self,
        store: ScheduleStore,
        user_id: int,
        offset: timedelta,
        step: int,
        state: _DateRangeState | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self._store = store
        self._user_id = user_id
        self._offset = offset
        self._step = step
        self._state = _DateRangeState() if state is None else state
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
            sel: Select[Any] = Select(
                options=opts, placeholder=f"Select {title}", row=0
            )
            sel.callback = self._on_pick
            self.add_item(sel)
        elif self._step == 2:  # noqa: PLR2004
            title = "Start Month"
            if self._state.sy == now.year:
                opts = [
                    discord.SelectOption(label=str(m), value=str(m))
                    for m in range(now.month, 13)
                ]
            else:
                opts = [
                    discord.SelectOption(label=str(m), value=str(m))
                    for m in range(1, 13)
                ]
            sel = Select(options=opts, placeholder=f"Select {title}", row=0)
            sel.callback = self._on_pick
            self.add_item(sel)
        elif self._step == 3:  # noqa: PLR2004
            min_day = (
                now.day
                if self._state.sy == now.year and self._state.sm == now.month
                else 1
            )
            self._make_day_select(
                "Start Day", self._state.sy, self._state.sm, min_day=min_day
            )
        elif self._step == 4:  # noqa: PLR2004
            title = "End Year"
            opts = [
                discord.SelectOption(label=str(y), value=str(y))
                for y in range(self._state.sy, self._state.sy + 5)
            ]
            sel = Select(options=opts, placeholder=f"Select {title}", row=0)
            sel.callback = self._on_pick
            self.add_item(sel)
        elif self._step == 5:  # noqa: PLR2004
            title = "End Month"
            if self._state.ey == self._state.sy:
                opts = [
                    discord.SelectOption(label=str(m), value=str(m))
                    for m in range(self._state.sm, 13)
                ]
            else:
                opts = [
                    discord.SelectOption(label=str(m), value=str(m))
                    for m in range(1, 13)
                ]
            sel = Select(options=opts, placeholder=f"Select {title}", row=0)
            sel.callback = self._on_pick
            self.add_item(sel)
        else:
            min_day = (
                self._state.sd
                if self._state.ey == self._state.sy
                and self._state.em == self._state.sm
                else 1
            )
            self._make_day_select(
                "End Day", self._state.ey, self._state.em, min_day=min_day
            )

    def _make_day_select(
        self, title: str, year: int, month: int, min_day: int = 1
    ) -> None:
        max_d = calendar.monthrange(year, month)[1]
        weeks: list[list[int]] = []
        current_week: list[int] = []
        for d in range(1, max_d + 1):
            current_week.append(d)
            if d == max_d or (
                calendar.weekday(year, month, d) == calendar.SUNDAY
            ):
                weeks.append(current_week)
                current_week = []
        for row, week_days in enumerate(weeks):
            start, end = week_days[0], week_days[-1]
            swd = calendar.day_abbr[calendar.weekday(year, month, start)]
            ewd = calendar.day_abbr[calendar.weekday(year, month, end)]
            chunk = [
                discord.SelectOption(
                    label=str(d),
                    value=str(d),
                    description=calendar.day_abbr[
                        calendar.weekday(year, month, d)
                    ],
                )
                for d in week_days
                if d >= min_day
            ]
            if not chunk:
                continue
            sel: Select[Any] = Select(
                options=chunk,
                placeholder=f"{title}: {swd} {start}-{ewd} {end}",
                row=row,
            )
            sel.callback = self._on_pick
            self.add_item(sel)

    async def _on_pick(self, interaction: Interaction) -> None:
        val = _first_val(interaction)
        if val is None:
            return

        if self._step == 1:
            nv = _ScheduleDatePickView(
                self._store,
                self._user_id,
                self._offset,
                2,
                replace(self._state, sy=int(val)),
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
                replace(self._state, sm=int(val)),
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
                replace(self._state, sd=int(val)),
            )
            await interaction.response.edit_message(
                content=(
                    f"Start date: **{self._state.sy}-{self._state.sm:02d}"
                    f"-{int(val):02d}**. Select end year:"
                ),
                view=nv,
            )
        elif self._step == 4:  # noqa: PLR2004
            nv = _ScheduleDatePickView(
                self._store,
                self._user_id,
                self._offset,
                5,
                replace(self._state, ey=int(val)),
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
                replace(self._state, em=int(val)),
            )
            await interaction.response.edit_message(
                content=f"End month: **{val}**. Select end day:", view=nv
            )
        else:
            end_day = int(val)
            try:
                start = date(self._state.sy, self._state.sm, self._state.sd)
                end = date(self._state.ey, self._state.em, end_day)
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

            configs: dict[int, list[tuple[str, str]]] = {}
            ctx = _ScheduleEditContext(
                store=self._store,
                user_id=self._user_id,
                offset=self._offset,
                dates=dates,
                configs=configs,
            )
            view = ScheduleDateConfigView(ctx)
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


@dataclass(frozen=True, slots=True)
class _ScheduleEditContext:
    """Context for schedule editing views."""

    store: ScheduleStore
    user_id: int
    offset: timedelta
    dates: list[date]
    configs: dict[int, list[tuple[str, str]]]


class ScheduleDateConfigView(NilesView):
    """Interactive view for per-date time configuration with buttons."""

    def __init__(self, ctx: _ScheduleEditContext) -> None:
        """Init."""
        super().__init__(timeout=300)
        self._ctx = ctx

        configured = sorted(
            [
                (i, d, ctx.configs[i])
                for i, d in enumerate(ctx.dates)
                if i in ctx.configs
            ],
            key=lambda x: x[0],
        )
        unconfigured = [
            (i, d) for i, d in enumerate(ctx.dates) if i not in ctx.configs
        ]

        for edit_row, batch in enumerate(_chunk(configured, 5)):
            for i, d, _windows in batch:
                btn: Button[Any] = Button(
                    label=f"Edit {d.strftime('%m/%d')}",
                    style=discord.ButtonStyle.primary,
                    row=edit_row,
                )
                btn.callback = self._make_edit_callback(i)
                self.add_item(btn)

        pick_row = 2
        for batch in _chunk(unconfigured, 5):
            for i, d in batch:
                btn: Button[Any] = Button(
                    label=d.strftime("%a %m/%d"),
                    style=discord.ButtonStyle.secondary,
                    row=pick_row,
                )
                btn.callback = self._make_date_callback(i)
                self.add_item(btn)
            pick_row += 1

        act_row = 4
        if unconfigured:
            iter_btn: Button[Any] = Button(
                label="Configure All Iteratively",
                style=discord.ButtonStyle.secondary,
                row=act_row,
            )
            iter_btn.callback = self._on_iterative
            self.add_item(iter_btn)
        if configured:
            confirm_btn: Button[Any] = Button(
                label="Confirm & Save",
                style=discord.ButtonStyle.success,
                row=act_row,
            )
            confirm_btn.callback = self._on_confirm
            self.add_item(confirm_btn)

    def _make_date_callback(self, idx: int):  # noqa: ANN202
        async def callback(interaction: Interaction) -> None:
            date_ = self._ctx.dates[idx]
            nv = ScheduleTimeFlowView(self._ctx, idx, date_, step=0)
            await interaction.response.edit_message(
                content=(
                    f"{_build_config_summary(self._ctx)}\n\n"
                    f"Configuring **{date_.strftime('%a %Y-%m-%d')}**."
                    f" Choose start hour:"
                ),
                view=nv,
            )

        return callback

    def _make_edit_callback(self, idx: int):  # noqa: ANN202
        async def callback(interaction: Interaction) -> None:
            date_ = self._ctx.dates[idx]
            nv = ScheduleTimeFlowView(self._ctx, idx, date_, step=0)
            await interaction.response.edit_message(
                content=(
                    f"{_build_config_summary(self._ctx)}\n\n"
                    f"Editing **{date_.strftime('%a %Y-%m-%d')}**. "
                    f"Choose start hour:"
                ),
                view=nv,
            )

        return callback

    async def _on_iterative(self, interaction: Interaction) -> None:
        """Start iterative configuration across all unconfigured dates."""
        unconfigured = [
            (i, d)
            for i, d in enumerate(self._ctx.dates)
            if i not in self._ctx.configs
        ]
        if not unconfigured:
            await interaction.response.defer()
            return
        first_idx, first_date = unconfigured[0]
        remaining = unconfigured[1:]
        nv = ScheduleTimeFlowView(
            self._ctx,
            first_idx,
            first_date,
            step=0,
            next_unconfigured=remaining,
        )
        await interaction.response.edit_message(
            content=(
                f"**Iterative mode** — configuring"
                f" **{first_date.strftime('%a %Y-%m-%d')}**.\n"
                f"Choose start hour:"
            ),
            view=nv,
        )

    async def _on_confirm(self, interaction: Interaction) -> None:
        """Generate windows from per-date configs and show preview."""
        windows: list[TimeWindow] = []
        user_tz = timezone(self._ctx.offset)
        for idx, windows_list in self._ctx.configs.items():
            d = self._ctx.dates[idx]
            for st, et in windows_list:
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
        preview = "\n".join(
            _fmt_range(w, self._ctx.offset) for w in preview_items
        )
        if len(windows_t) > _PREVIEW_LIMIT:
            preview += f"\n... and {len(windows_t) - _PREVIEW_LIMIT} more"

        view = ConfirmWindowsView(self._ctx.store, self._ctx.user_id, windows_t)
        msg = (
            f"Generated {len(windows_t)} windows:\n"
            f"```\n{preview}\n```\nConfirm?"
        )
        await interaction.response.send_message(msg, view=view, ephemeral=True)


class ScheduleTimeSelectView(NilesView):
    """Select start/end times for a specific date via hour/minute selects."""

    def __init__(
        self,
        ctx: _ScheduleEditContext,
        date_idx: int,
        date_: date,
        known: (
            tuple[int | None, int | None, int | None, int | None] | None
        ) = None,
    ) -> None:
        """Init."""
        super().__init__(timeout=300)
        self._ctx = ctx
        self._date_idx = date_idx
        self._date = date_

        if known is not None:
            self._start_h, self._start_m, self._end_h, self._end_m = known
            ds_h = known[0] if known[0] is not None else 9
            ds_m = known[1] if known[1] is not None else 0
            de_h = known[2] if known[2] is not None else 17
            de_m = known[3] if known[3] is not None else 0
        else:
            self._start_h = None
            self._start_m = None
            self._end_h = None
            self._end_m = None
            ds_h, ds_m, de_h, de_m = 9, 0, 17, 0

        hour_opts = [
            discord.SelectOption(label=f"{h:02d}", value=str(h))
            for h in range(24)
        ]
        min_opts = [
            discord.SelectOption(label=f"{m:02d}", value=str(m))
            for m in (0, 15, 30, 45)
        ]

        self._sh_sel: Select[Any] = Select(
            options=self._mark_default(hour_opts, str(ds_h)),
            placeholder="Start hour",
            row=0,
        )
        self._sh_sel.callback = self._on_sh
        self.add_item(self._sh_sel)

        self._sm_sel: Select[Any] = Select(
            options=self._mark_default(min_opts, str(ds_m)),
            placeholder="Start minute",
            row=1,
        )
        self._sm_sel.callback = self._on_sm
        self.add_item(self._sm_sel)

        if self._start_h is not None:
            end_hour_opts = [
                discord.SelectOption(label=f"{h:02d}", value=str(h))
                for h in range(self._start_h, 24)
            ]
        else:
            end_hour_opts = hour_opts

        self._eh_sel: Select[Any] = Select(
            options=self._mark_default(end_hour_opts, str(de_h)),
            placeholder="End hour",
            row=2,
        )
        self._eh_sel.callback = self._on_eh
        self.add_item(self._eh_sel)

        if (
            self._start_h is not None
            and self._start_m is not None
            and self._end_h is not None
            and self._end_h == self._start_h
        ):
            end_min_opts = [
                discord.SelectOption(label=f"{m:02d}", value=str(m))
                for m in (0, 15, 30, 45)
                if m > self._start_m
            ] or min_opts
        else:
            end_min_opts = min_opts

        self._em_sel: Select[Any] = Select(
            options=self._mark_default(end_min_opts, str(de_m)),
            placeholder="End minute",
            row=3,
        )
        self._em_sel.callback = self._on_em
        self.add_item(self._em_sel)

    @staticmethod
    def _mark_default(
        options: list[discord.SelectOption], value: str
    ) -> list[discord.SelectOption]:
        """Mark the matching option as default."""
        return [
            o
            if o.value != value
            else discord.SelectOption(
                label=o.label, value=o.value, default=True
            )
            for o in options
        ]

    async def _on_sh(self, interaction: Interaction) -> None:
        val = int(self._sh_sel.values[0])
        if val == self._start_h:
            await interaction.response.defer()
            return
        view = ScheduleTimeSelectView(
            self._ctx,
            self._date_idx,
            self._date,
            (val, self._start_m, self._end_h, self._end_m),
        )
        await interaction.response.edit_message(view=view)

    async def _on_sm(self, interaction: Interaction) -> None:
        val = int(self._sm_sel.values[0])
        if val == self._start_m:
            await interaction.response.defer()
            return
        view = ScheduleTimeSelectView(
            self._ctx,
            self._date_idx,
            self._date,
            (self._start_h, val, self._end_h, self._end_m),
        )
        await interaction.response.edit_message(view=view)

    async def _on_eh(self, interaction: Interaction) -> None:
        val = int(self._eh_sel.values[0])
        if val == self._end_h:
            await interaction.response.defer()
            return
        view = ScheduleTimeSelectView(
            self._ctx,
            self._date_idx,
            self._date,
            (self._start_h, self._start_m, val, self._end_m),
        )
        await interaction.response.edit_message(view=view)

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
                content=(
                    "End time must be after start time."
                    f" Set time for **{self._date.strftime('%a %Y-%m-%d')}**:"
                ),
                view=ScheduleTimeSelectView(
                    self._ctx, self._date_idx, self._date, (sh, sm, eh, em)
                ),
            )
            return

        new_configs = {**self._ctx.configs, self._date_idx: [(st, et)]}
        new_ctx = replace(self._ctx, configs=new_configs)
        new_view = ScheduleDateConfigView(new_ctx)
        await interaction.response.edit_message(
            content=_build_config_summary(new_ctx), view=new_view
        )


class ScheduleTimeFlowView(NilesView):
    """Step-by-step time selection with 12h AM/PM buttons."""

    def __init__(  # noqa: PLR0913
        self,
        ctx: _ScheduleEditContext,
        date_idx: int,
        date_: date,
        step: int = 0,
        start_h: int | None = None,
        start_m: int | None = None,
        end_h: int | None = None,
        end_m: int | None = None,
        next_unconfigured: list[tuple[int, date]] | None = None,
    ) -> None:
        """Init."""
        super().__init__(timeout=300)
        self._ctx = ctx
        self._date_idx = date_idx
        self._date = date_
        self._step = step
        self._start_h = start_h
        self._start_m = start_m
        self._end_h = end_h
        self._end_m = end_m
        self._next_unconfigured = next_unconfigured

        if step == 0:
            self._build_start_hour_buttons()
        elif step == 1:
            self._build_minute_buttons(is_start=True)
        elif step == 2:  # noqa: PLR2004
            self._build_end_hour_buttons()
        elif step == 3:  # noqa: PLR2004
            self._build_minute_buttons(is_start=False)
        elif step == 4:  # noqa: PLR2004
            self._build_post_time_buttons()

        if 0 < step < 4:  # noqa: PLR2004
            self._add_back_button()
        if step == 4:  # noqa: PLR2004
            self._add_back_button(row=1)
        self._add_cancel_button()

    @staticmethod
    def _to_12h(h24: int) -> tuple[int, str]:
        if h24 == 0:
            return (12, "AM")
        if h24 < 12:  # noqa: PLR2004
            return (h24, "AM")
        if h24 == 12:  # noqa: PLR2004
            return (12, "PM")
        return (h24 - 12, "PM")

    @staticmethod
    def _fmt_hour(h24: int) -> str:
        h12, ampm = ScheduleTimeFlowView._to_12h(h24)
        return f"{h12}{ampm}"

    @staticmethod
    def _fmt_time(h: int, m: int) -> str:
        return f"{ScheduleTimeFlowView._fmt_hour(h)}:{m:02d}"

    def _last_content_row(self) -> int:
        if self._step == 0:
            return 4
        if self._step == 1:
            return 0
        if self._step == 2:  # noqa: PLR2004
            min_h = cast("int", self._start_h) + (
                1 if self._start_m is not None and self._start_m >= 45 else 0  # noqa: PLR2004
            )
            count = max(24 - min_h, 0)
            if count == 0:
                return 0
            return (count - 1) // 5
        return 0

    def _add_back_button(self, row: int | None = None) -> None:
        if row is not None:
            back = Button[Any](
                label="Back", style=discord.ButtonStyle.secondary, row=row
            )
            back.callback = self._on_back
            self.add_item(back)
        else:
            last_row = self._last_content_row()
            if last_row < 4:  # noqa: PLR2004
                back = Button[Any](
                    label="Back",
                    style=discord.ButtonStyle.secondary,
                    row=last_row + 1,
                )
                back.callback = self._on_back
                self.add_item(back)

    def _add_cancel_button(self) -> None:
        cancel = Button[Any](
            label="Cancel", style=discord.ButtonStyle.danger, row=4
        )
        cancel.callback = self._on_cancel
        self.add_item(cancel)

    def _build_post_time_buttons(self) -> None:
        add_btn: Button[Any] = Button(
            label="Add Another Window", style=discord.ButtonStyle.primary, row=0
        )
        add_btn.callback = self._on_add_another
        self.add_item(add_btn)

        done_label = "Next Day →" if self._next_unconfigured else "Done"
        done_btn: Button[Any] = Button(
            label=done_label, style=discord.ButtonStyle.secondary, row=0
        )
        done_btn.callback = self._on_done
        self.add_item(done_btn)

    def _build_start_hour_buttons(self) -> None:
        for h24 in range(24):
            button = Button[Any](
                label=self._fmt_hour(h24),
                style=discord.ButtonStyle.secondary,
                row=h24 // 5,
            )
            button.callback = self._make_hour_callback(h24, is_start=True)
            self.add_item(button)

    def _make_hour_callback(self, h24: int, *, is_start: bool):  # noqa: ANN202
        async def callback(interaction: Interaction) -> None:
            if is_start:
                nv = ScheduleTimeFlowView(
                    self._ctx,
                    self._date_idx,
                    self._date,
                    step=1,
                    start_h=h24,
                    next_unconfigured=self._next_unconfigured,
                )
                content = (
                    f"Start hour: **{self._fmt_hour(h24)}**. "
                    f"Choose start minute:"
                )
            else:
                nv = ScheduleTimeFlowView(
                    self._ctx,
                    self._date_idx,
                    self._date,
                    step=3,
                    start_h=self._start_h,
                    start_m=self._start_m,
                    end_h=h24,
                    next_unconfigured=self._next_unconfigured,
                )
                content = (
                    f"End hour: **{self._fmt_hour(h24)}**. Choose end minute:"
                )
            await interaction.response.edit_message(content=content, view=nv)

        return callback

    def _build_minute_buttons(self, *, is_start: bool) -> None:
        min_val: int = (
            -1
            if is_start
            else (
                cast("int", self._start_m)
                if self._end_h == self._start_h
                else -1
            )
        )
        for m in (0, 15, 30, 45):
            if m <= min_val and not is_start and self._end_h == self._start_h:
                continue
            button = Button[Any](
                label=f"{m:02d}", style=discord.ButtonStyle.secondary, row=0
            )
            button.callback = self._make_min_callback(m, is_start=is_start)
            self.add_item(button)

    def _make_min_callback(self, m: int, *, is_start: bool):  # noqa: ANN202
        async def callback(interaction: Interaction) -> None:
            if is_start:
                nv = ScheduleTimeFlowView(
                    self._ctx,
                    self._date_idx,
                    self._date,
                    step=2,
                    start_h=self._start_h,
                    start_m=m,
                    next_unconfigured=self._next_unconfigured,
                )
                content = (
                    f"Start time: "
                    f"**{self._fmt_time(cast('int', self._start_h), m)}**. "
                    f"Choose end hour:"
                )
                await interaction.response.edit_message(
                    content=content, view=nv
                )
            else:
                await self._on_end_minute(interaction, m)

        return callback

    async def _on_end_minute(self, interaction: Interaction, m: int) -> None:
        st = f"{self._start_h:02d}:{self._start_m:02d}"
        et = f"{self._end_h:02d}:{m:02d}"
        existing = self._ctx.configs.get(self._date_idx, [])
        new_configs = {
            **self._ctx.configs,
            self._date_idx: [*existing, (st, et)],
        }
        new_ctx = replace(self._ctx, configs=new_configs)
        nv = ScheduleTimeFlowView(
            new_ctx,
            self._date_idx,
            self._date,
            step=4,
            next_unconfigured=self._next_unconfigured,
        )
        windows_str = _fmt_windows(new_ctx.configs[self._date_idx])
        content = (
            f"Saved window **{st} - {et}**"
            f" for **{self._date.strftime('%a %Y-%m-%d')}**.\n"
            f"Current windows: {windows_str}\n"
            f"What next?"
        )
        await interaction.response.edit_message(content=content, view=nv)

    async def _on_add_another(self, interaction: Interaction) -> None:
        nv = ScheduleTimeFlowView(
            self._ctx,
            self._date_idx,
            self._date,
            step=0,
            next_unconfigured=self._next_unconfigured,
        )
        await interaction.response.edit_message(
            content=(
                f"{_build_config_summary(self._ctx)}\n\n"
                f"Adding another window for"
                f" **{self._date.strftime('%a %Y-%m-%d')}**.\n"
                f"Choose start hour:"
            ),
            view=nv,
        )

    async def _on_done(self, interaction: Interaction) -> None:
        if self._next_unconfigured:
            next_idx, next_date = self._next_unconfigured[0]
            remaining = self._next_unconfigured[1:]
            nv = ScheduleTimeFlowView(
                self._ctx,
                next_idx,
                next_date,
                step=0,
                next_unconfigured=remaining,
            )
            await interaction.response.edit_message(
                content=(
                    f"**Iterative mode** — configuring"
                    f" **{next_date.strftime('%a %Y-%m-%d')}**.\n"
                    f"Choose start hour:"
                ),
                view=nv,
            )
        else:
            nv = ScheduleDateConfigView(self._ctx)
            await interaction.response.edit_message(
                content=_build_config_summary(self._ctx), view=nv
            )

    def _build_end_hour_buttons(self) -> None:
        min_h24 = cast("int", self._start_h) + (
            1 if self._start_m is not None and self._start_m >= 45 else 0  # noqa: PLR2004
        )
        count = max(24 - min_h24, 0)
        if count == 0:
            button = Button[Any](
                label="No valid end hour - Go Back",
                style=discord.ButtonStyle.danger,
                row=0,
            )
            button.callback = self._on_back
            self.add_item(button)
            return

        for i, h24 in enumerate(range(min_h24, 24)):
            button = Button[Any](
                label=self._fmt_hour(h24),
                style=discord.ButtonStyle.secondary,
                row=i // 5,
            )
            button.callback = self._make_hour_callback(h24, is_start=False)
            self.add_item(button)

    async def _on_back(self, interaction: Interaction) -> None:
        if self._step == 1:
            nv = ScheduleTimeFlowView(
                self._ctx,
                self._date_idx,
                self._date,
                step=0,
                next_unconfigured=self._next_unconfigured,
            )
            content = "Choose start hour:"
        elif self._step == 2:  # noqa: PLR2004
            nv = ScheduleTimeFlowView(
                self._ctx,
                self._date_idx,
                self._date,
                step=1,
                start_h=self._start_h,
                next_unconfigured=self._next_unconfigured,
            )
            content = (
                f"Start hour: "
                f"**{self._fmt_hour(cast('int', self._start_h))}**. "
                f"Choose start minute:"
            )
        elif self._step == 3:  # noqa: PLR2004
            nv = ScheduleTimeFlowView(
                self._ctx,
                self._date_idx,
                self._date,
                step=2,
                start_h=self._start_h,
                start_m=self._start_m,
                next_unconfigured=self._next_unconfigured,
            )
            sh = cast("int", self._start_h)
            sm = cast("int", self._start_m)
            content = (
                f"Start time: **{self._fmt_time(sh, sm)}**. Choose end hour:"
            )
        elif self._step == 4:  # noqa: PLR2004
            nv = ScheduleDateConfigView(self._ctx)
            await interaction.response.edit_message(
                content=_build_config_summary(self._ctx), view=nv
            )
            return
        else:
            return
        await interaction.response.edit_message(content=content, view=nv)

    async def _on_cancel(self, interaction: Interaction) -> None:
        nv = ScheduleDateConfigView(self._ctx)
        await interaction.response.edit_message(
            content=_build_config_summary(self._ctx), view=nv
        )


class ConfirmWindowsView(NilesView):
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
            cast("Any", child).disabled = True
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(
        self, interaction: Interaction, _button: Button[Any]
    ) -> None:
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
    async def cancel(
        self, interaction: Interaction, _button: Button[Any]
    ) -> None:
        """Cancel adding windows."""
        LOGGER.info(
            "User {} cancelled adding {} free time windows",
            interaction.user.id,
            len(self._windows),
        )
        await self._disable_all(interaction)
        await interaction.edit_original_response(content="Cancelled.")


class RemoveSelect(NilesView):
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
        options: list[discord.SelectOption] = []
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
        select: Select[Any] = Select(
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


class RemoveReasonView(NilesView):
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
        sel: Select[Any] = Select(
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


class ClearConfirmView(NilesView):
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
        """Show reason select for clearing."""
        LOGGER.info("User {} initiated clear all entries", interaction.user.id)
        view = ClearReasonView(self._store, self._user_id)
        await interaction.response.edit_message(
            content="Clear all future entries? Select a reason or skip:",
            view=view,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(
        self, interaction: Interaction, _button: Button[Any]
    ) -> None:
        """Cancel clearing."""
        LOGGER.info("User {} cancelled clearing entries", interaction.user.id)
        for child in self.children:
            cast("Any", child).disabled = True
        await interaction.response.edit_message(content="Cancelled.", view=self)


class ClearReasonView(NilesView):
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
        sel: Select[Any] = Select(
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

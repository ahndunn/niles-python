"""Timezone setup UI components."""
# pyright: reportMissingTypeArgument=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false

from datetime import timedelta
from typing import ClassVar

import discord
from discord import Interaction
from discord.ui import Button
from discord.ui import View

from niles.discord.stores import get_timezone_store
from niles.utils.datetime import parse_offset
from niles.utils.loggers import LOGGER


async def ensure_timezone(interaction: Interaction) -> timedelta | None:
    """Check user has a timezone set; send setup view if not.

    Returns the user's offset as a ``timedelta``, or ``None`` if the view was
    sent (handler should return early).
    """
    store = get_timezone_store(interaction)
    if store is None:
        return timedelta(0)
    offset_str = store.get(interaction.user.id)
    if offset_str is not None:
        parsed = parse_offset(offset_str)
        if parsed is not None:
            return parsed
        store.set(interaction.user.id, "UTC+0")
        return timedelta(0)
    view = TimezoneChangePrompt()
    await interaction.response.send_message(
        "Your timezone is set to **UTC+0** by default. "
        "Would you like to change it?",
        view=view,
        ephemeral=True,
    )
    return None


class TimezoneChangePrompt(View):
    """Step 1: Ask if user wants to change from default UTC+0."""

    def __init__(self) -> None:
        """Init."""
        super().__init__(timeout=300)

    @discord.ui.button(
        label="Yes, change timezone", style=discord.ButtonStyle.primary
    )
    async def _yes_change(
        self, interaction: Interaction, _button: Button
    ) -> None:
        """User wants to change timezone."""
        view = TimezoneSignSelect()
        await interaction.response.edit_message(
            content="Is your timezone positive or negative (relative to UTC)?",
            view=view,
        )
        self.stop()

    @discord.ui.button(
        label="No, keep UTC+0", style=discord.ButtonStyle.secondary
    )
    async def _no_keep(self, interaction: Interaction, _button: Button) -> None:
        """Keep default UTC+0."""
        store = get_timezone_store(interaction)
        if store is not None:
            store.set(interaction.user.id, "UTC+0")
        LOGGER.info("Timezone set for user {}: UTC+0", interaction.user.id)
        await interaction.response.edit_message(
            content="✅ Timezone set to **UTC+0**.", view=None
        )
        self.stop()


class TimezoneSignSelect(View):
    """Step 2: Choose positive or negative offset."""

    def __init__(self) -> None:
        """Init."""
        super().__init__(timeout=300)

    @discord.ui.button(
        label="Positive (UTC+0 to UTC+14)", style=discord.ButtonStyle.success
    )
    async def _positive(
        self, interaction: Interaction, _button: Button
    ) -> None:
        """User chose positive offset."""
        view = TimezoneHourSelect("+")
        await interaction.response.edit_message(
            content="Select your UTC hour offset:", view=view
        )
        self.stop()

    @discord.ui.button(
        label="Negative (UTC-1 to UTC-12)", style=discord.ButtonStyle.danger
    )
    async def _negative(
        self, interaction: Interaction, _button: Button
    ) -> None:
        """User chose negative offset."""
        view = TimezoneHourSelect("-")
        await interaction.response.edit_message(
            content="Select your UTC hour offset:", view=view
        )
        self.stop()


class TimezoneHourSelect(View):
    """Step 3: Select the hour offset."""

    _SPECIAL_MINUTES: ClassVar[dict[str, dict[int, tuple[int, ...]]]] = {
        "-": {3: (0, 30), 9: (0, 30)},
        "+": {
            3: (0, 30),
            4: (0, 30),
            5: (0, 30, 45),
            6: (0, 30),
            8: (0, 45),
            9: (0, 30),
            10: (0, 30),
            12: (0, 45),
        },
    }

    def __init__(self, sign: str) -> None:
        """Init."""
        super().__init__(timeout=300)
        self._sign = sign

        hours = list(range(15)) if sign == "+" else list(range(1, 13))

        options = [
            discord.SelectOption(label=f"UTC{sign}{h}", value=str(h))
            for h in hours
        ]
        self._hour_select = discord.ui.Select(
            placeholder="Select hour offset...", options=options
        )
        self._hour_select.callback = self._on_hour_select
        self.add_item(self._hour_select)

    async def _on_hour_select(self, interaction: Interaction) -> None:
        """Handle hour selection."""
        hour = int(self._hour_select.values[0])
        sign = self._sign
        special = self._SPECIAL_MINUTES.get(sign, {}).get(hour)

        if special is None:
            offset_str = f"UTC{sign}{hour}"
            store = get_timezone_store(interaction)
            if store is not None:
                store.set(interaction.user.id, offset_str)
            LOGGER.info(
                "Timezone set for user {}: {}", interaction.user.id, offset_str
            )
            await interaction.response.edit_message(
                content=f"✅ Timezone set to **{offset_str}**.", view=None
            )
        else:
            view = TimezoneMinuteSelect(sign, hour, special)
            await interaction.response.edit_message(
                content="Select the minute offset:", view=view
            )
        self.stop()


class TimezoneMinuteSelect(View):
    """Step 4: Select the minute offset for special hours."""

    def __init__(
        self, sign: str, hour: int, minute_options: tuple[int, ...]
    ) -> None:
        """Init."""
        super().__init__(timeout=300)
        self._sign = sign
        self._hour = hour

        options = [
            discord.SelectOption(
                label=(
                    f"UTC{sign}{hour}" if m == 0 else f"UTC{sign}{hour}:{m:02d}"
                ),
                value=str(m),
            )
            for m in minute_options
        ]
        self._minute_select = discord.ui.Select(
            placeholder="Select minute offset...", options=options
        )
        self._minute_select.callback = self._on_minute_select
        self.add_item(self._minute_select)

    async def _on_minute_select(self, interaction: Interaction) -> None:
        """Handle minute selection."""
        minute = int(self._minute_select.values[0])
        sign = self._sign
        hour = self._hour

        if minute == 0:
            offset_str = f"UTC{sign}{hour}"
        else:
            offset_str = f"UTC{sign}{hour}:{minute:02d}"

        store = get_timezone_store(interaction)
        if store is not None:
            store.set(interaction.user.id, offset_str)
        LOGGER.info(
            "Timezone set for user {}: {}", interaction.user.id, offset_str
        )
        await interaction.response.edit_message(
            content=f"✅ Timezone set to **{offset_str}**.", view=None
        )
        self.stop()

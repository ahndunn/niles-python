"""Timezone setup UI components."""

from collections.abc import Awaitable
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import discord
from discord import Interaction

from niles.discord.stores import get_timezone_store
from niles.discord.views.base import NilesView
from niles.utils.datetime import parse_offset
from niles.utils.loggers import LOGGER

if TYPE_CHECKING:
    from discord.ui import Button
    from discord.ui import Select

_MAX_DESCRIPTION_COUNTRIES: Final[int] = 2

type CommandContinuation = Callable[[Interaction, timedelta], Awaitable[None]]

TIMEZONE_REGIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "Africa": {
        "UTC-01": ("Cabo Verde",),
        "UTC+00": ("Ghana", "Ivory Coast", "Morocco", "Senegal"),
        "UTC+01": ("Nigeria", "Algeria", "Tunisia", "Angola"),
        "UTC+02": ("South Africa", "Zimbabwe", "Botswana", "Mozambique"),
        "UTC+03": ("Kenya", "Ethiopia", "Tanzania", "Uganda"),
        "UTC+04": ("Mauritius", "Seychelles"),
    },
    "Asia": {
        "UTC+02": ("Jerusalem", "Amman", "Beirut"),
        "UTC+03": ("Riyadh", "Baghdad", "Kuwait", "Qatar"),
        "UTC+03:30": ("Tehran",),
        "UTC+04": ("Dubai", "Baku", "Tbilisi", "Muscat"),
        "UTC+04:30": ("Kabul",),
        "UTC+05": ("Karachi", "Tashkent", "Maldives"),
        "UTC+05:30": ("India", "Sri Lanka"),
        "UTC+05:45": ("Kathmandu",),
        "UTC+06": ("Dhaka", "Almaty"),
        "UTC+06:30": ("Yangon",),
        "UTC+07": ("Bangkok", "Jakarta", "Ho Chi Minh City"),
        "UTC+08": ("Beijing", "Singapore", "Taipei", "Kuala Lumpur"),
        "UTC+09": ("Tokyo", "Seoul"),
        "UTC+09:30": ("Darwin",),
        "UTC+10": ("Vladivostok", "Port Moresby"),
        "UTC+11": ("Sydney", "Melbourne", "Hobart"),
        "UTC+12": ("Kamchatka",),
    },
    "Atlantic": {
        "UTC-02": ("King Edward Point",),
        "UTC-01": ("Azores",),
        "UTC+00": ("Canary Islands", "Madeira"),
    },
    "Australia": {
        "UTC+08": ("Perth",),
        "UTC+08:45": ("Eucla",),
        "UTC+09:30": ("Darwin",),
        "UTC+10": ("Brisbane",),
        "UTC+10:30": ("Adelaide",),
        "UTC+11": ("Sydney", "Melbourne", "Hobart", "Canberra"),
    },
    "Europe": {
        "UTC+00": ("London", "Dublin", "Lisbon", "Reykjavik"),
        "UTC+01": ("Paris", "Berlin", "Rome", "Madrid"),
        "UTC+02": ("Helsinki", "Athens", "Bucharest", "Kyiv"),
        "UTC+03": ("Moscow", "Istanbul", "Minsk"),
    },
    "North America": {
        "UTC-10": ("Honolulu",),
        "UTC-09": ("Anchorage",),
        "UTC-08": ("Los Angeles", "Vancouver"),
        "UTC-07": ("Denver", "Phoenix", "Edmonton"),
        "UTC-06": ("Chicago", "Mexico City", "Dallas"),
        "UTC-05": ("New York", "Toronto", "Miami"),
        "UTC-04": ("Halifax",),
        "UTC-03": ("Nuuk",),
        "UTC-03:30": ("St. John's",),
    },
    "Pacific": {
        "UTC-11": ("Pago Pago",),
        "UTC-10": ("Tahiti",),
        "UTC-09": ("Gambier",),
        "UTC-08": ("Pitcairn",),
        "UTC-06": ("Easter Island",),
        "UTC-05": ("Galapagos",),
        "UTC+12": ("Auckland", "Fiji"),
        "UTC+13": ("Samoa", "Tonga"),
        "UTC+14": ("Kiritimati",),
    },
    "South America": {
        "UTC-05": ("Bogota", "Lima", "Quito"),
        "UTC-04": ("La Paz", "Georgetown", "Manaus"),
        "UTC-03": ("Buenos Aires", "Sao Paulo", "Santiago"),
        "UTC-02": ("Fernando de Noronha",),
    },
}


def _sort_offset_key(offset_str: str) -> int:
    parsed = parse_offset(offset_str)
    if parsed is None:
        return 0
    return int(parsed.total_seconds() / 60)


def _format_description(countries: tuple[str, ...]) -> str:
    if len(countries) <= _MAX_DESCRIPTION_COUNTRIES:
        return ", ".join(countries)
    return f"{countries[0]}, {countries[1]}, ..."


async def ensure_timezone(
    interaction: Interaction, on_complete: CommandContinuation | None = None
) -> timedelta | None:
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
        store.set(interaction.user.id, "UTC+00")
        return timedelta(0)
    view = TimezoneSetupView(on_complete=on_complete)
    await interaction.response.send_message(
        "You haven't set a timezone yet. Currently using **UTC+00**. "
        "Select a region below to choose your timezone.",
        view=view,
        ephemeral=True,
    )
    return None


class TimezoneSetupView(NilesView):
    """Step 1: Select a region to filter timezones."""

    def __init__(self, on_complete: CommandContinuation | None = None) -> None:
        """Init."""
        super().__init__(timeout=300)
        self._on_complete = on_complete

        options = [
            discord.SelectOption(label=region, value=region)
            for region in sorted(TIMEZONE_REGIONS)
        ]
        self._region_select: Select[Any] = discord.ui.Select(
            placeholder="Select a region...", options=options
        )
        self._region_select.callback = self._on_region_select
        self.add_item(self._region_select)

    @discord.ui.button(label="Keep UTC+00", style=discord.ButtonStyle.secondary)
    async def _keep_default(
        self, interaction: Interaction, _button: Button[Any]
    ) -> None:
        store = get_timezone_store(interaction)
        if store is not None:
            store.set(interaction.user.id, "UTC+00")
        LOGGER.info("Timezone set for user {}: UTC+00", interaction.user.id)
        await interaction.response.edit_message(
            content="Timezone set to **UTC+00**.", view=None
        )
        if self._on_complete is not None:
            await self._on_complete(interaction, timedelta(0))
        self.stop()

    async def _on_region_select(self, interaction: Interaction) -> None:
        region = self._region_select.values[0]
        view = TimezonePickerView(region, on_complete=self._on_complete)
        await interaction.response.edit_message(
            content=f"Select your timezone for **{region}**:", view=view
        )
        self.stop()


class TimezonePickerView(NilesView):
    """Step 2: Select a timezone from the chosen region."""

    def __init__(
        self, region: str, on_complete: CommandContinuation | None = None
    ) -> None:
        """Init."""
        super().__init__(timeout=300)
        self._region = region
        self._on_complete = on_complete

        timezones = TIMEZONE_REGIONS[region]
        options = [
            discord.SelectOption(
                label=offset_str,
                description=_format_description(countries),
                value=offset_str,
            )
            for offset_str, countries in sorted(
                timezones.items(), key=lambda x: _sort_offset_key(x[0])
            )
        ]
        self._tz_select: Select[Any] = discord.ui.Select(
            placeholder="Select your timezone...", options=options
        )
        self._tz_select.callback = self._on_tz_select
        self.add_item(self._tz_select)

    @discord.ui.button(
        label="Back to regions", style=discord.ButtonStyle.secondary
    )
    async def _back(
        self, interaction: Interaction, _button: Button[Any]
    ) -> None:
        view = TimezoneSetupView(on_complete=self._on_complete)
        await interaction.response.edit_message(
            content="Select a region below to choose your timezone:", view=view
        )
        self.stop()

    async def _on_tz_select(self, interaction: Interaction) -> None:
        offset_str = self._tz_select.values[0]
        store = get_timezone_store(interaction)
        if store is not None:
            store.set(interaction.user.id, offset_str)
        LOGGER.info(
            "Timezone set for user {}: {}", interaction.user.id, offset_str
        )
        await interaction.response.edit_message(
            content=f"Timezone set to **{offset_str}**.", view=None
        )
        if self._on_complete is not None:
            parsed = parse_offset(offset_str)
            if parsed is not None:
                await self._on_complete(interaction, parsed)
        self.stop()

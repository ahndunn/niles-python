"""Timezone commands."""

from discord import Interaction
from discord import app_commands

from niles.discord.stores import get_timezone_store
from niles.utils.datetime import format_offset
from niles.utils.datetime import parse_offset
from niles.utils.loggers import LOGGER

timezone_group = app_commands.Group(
    name="timezone", description="Manage your timezone"
)


@timezone_group.command(name="set", description="Set your UTC offset")
async def timezone_set(interaction: Interaction, offset: str) -> None:
    """Set your timezone offset."""
    parsed = parse_offset(offset)
    if parsed is None:
        await interaction.response.send_message(
            f"Invalid offset: '{offset}'. "
            "Use format like UTC+5, UTC-3, UTC+5:30.",
            ephemeral=True,
        )
        return
    store = get_timezone_store(interaction)
    if store is None:
        await interaction.response.send_message(
            "Store not available.", ephemeral=True
        )
        return
    formatted = format_offset(parsed)
    store.set(interaction.user.id, formatted)
    LOGGER.info("User {} set timezone to {}", interaction.user.id, formatted)
    await interaction.response.send_message(
        f"✅ Timezone set to {formatted}.", ephemeral=True
    )


@timezone_group.command(name="view", description="View your current timezone")
async def timezone_view(interaction: Interaction) -> None:
    """View your current timezone offset."""
    store = get_timezone_store(interaction)
    if store is None:
        await interaction.response.send_message(
            "Store not available.", ephemeral=True
        )
        return
    offset_str = store.get(interaction.user.id)
    if offset_str is None:
        await interaction.response.send_message(
            "No timezone set. Run any command to set up, or use /timezone set.",
            ephemeral=True,
        )
        return
    parsed = parse_offset(offset_str)
    if parsed is not None:
        offset_str = format_offset(parsed)
    await interaction.response.send_message(
        f"Your timezone: {offset_str}", ephemeral=True
    )

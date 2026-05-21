"""On disconnect."""

from typing import TYPE_CHECKING

from niles.utils.loggers import LOGGER

if TYPE_CHECKING:
    import discord


async def on_disconnect(_client: discord.Client) -> None:
    """On disconnect."""
    LOGGER.warning("Niles disconnected from Discord gateway")

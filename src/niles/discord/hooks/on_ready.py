"""On ready."""

from typing import TYPE_CHECKING

from niles.utils.loggers import LOGGER

if TYPE_CHECKING:
    import discord


async def on_ready(client: discord.Client) -> None:
    """On ready."""
    if client.user:
        LOGGER.info(
            "Niles logged in as {} in {} guild(s)",
            client.user,
            len(client.guilds),
        )

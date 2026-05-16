"""On message."""

from typing import TYPE_CHECKING

from niles.utils.loggers import LOGGER

if TYPE_CHECKING:
    import discord


async def on_message(_client: discord.Client, message: discord.Message) -> None:
    """On message."""
    LOGGER.debug(
        "Message from {} in {}: {}",
        message.author,
        message.channel,
        message.content[:80] if message.content else "(no content)",
    )

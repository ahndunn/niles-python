"""On message."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord


async def on_message(client: discord.Client, message: discord.Message) -> None:
    """On message."""
    raise NotImplementedError

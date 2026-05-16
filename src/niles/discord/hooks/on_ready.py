"""On ready."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord


async def on_ready(client: discord.Client) -> None:
    """On ready."""
    raise NotImplementedError

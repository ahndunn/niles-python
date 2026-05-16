"""On disconnect."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord


async def on_disconnect(client: discord.Client) -> None:
    """On disconnect."""
    raise NotImplementedError

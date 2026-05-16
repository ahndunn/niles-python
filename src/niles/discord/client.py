"""Client."""

from typing import final

import discord
from discord.ext import commands

from niles.discord.commands import setup_commands
from niles.discord.hooks.on_disconnect import on_disconnect as _on_disconnect
from niles.discord.hooks.on_message import on_message as _on_message
from niles.discord.hooks.on_ready import on_ready as _on_ready
from niles.discord.stores import EventStore
from niles.discord.stores import ScheduleStore
from niles.utils.loggers import LOGGER


@final
class NilesClient(commands.Bot):
    """Niles client."""

    def __init__(self) -> None:
        """Init."""
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix=(), intents=intents)
        self.schedules: ScheduleStore = ScheduleStore()
        self.events: EventStore = EventStore()

    async def on_ready(self) -> None:
        """On ready."""
        setup_commands(self.tree)
        await self.tree.sync()
        LOGGER.info(
            "Niles is ready! (user={}, guilds={})", self.user, len(self.guilds)
        )
        await _on_ready(self)

    async def on_message(self, message: discord.Message) -> None:
        """On message."""
        LOGGER.debug(
            "Message from {} in {}: {}",
            message.author,
            message.channel,
            message.content[:80] if message.content else "(no content)",
        )
        await _on_message(self, message)

    async def on_disconnect(self) -> None:
        """On disconnect."""
        LOGGER.warning("Niles disconnected from Discord gateway")
        await _on_disconnect(self)

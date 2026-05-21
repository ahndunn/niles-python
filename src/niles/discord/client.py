"""Client."""

from typing import TYPE_CHECKING
from typing import final

import discord
from discord import Interaction
from discord.ext import commands

from niles.discord.commands import setup_commands
from niles.discord.databases.event import EventStore
from niles.discord.databases.pending import PendingConfirmationStore
from niles.discord.databases.schedule import ScheduleStore
from niles.discord.databases.timezone import TimezoneStore
from niles.discord.hooks.on_disconnect import on_disconnect as _on_disconnect
from niles.discord.hooks.on_message import on_message as _on_message
from niles.discord.hooks.on_ready import on_ready as _on_ready
from niles.utils.loggers import LOGGER

if TYPE_CHECKING:
    from discord.app_commands import AppCommandError


@final
class NilesClient(commands.Bot):
    """Niles client."""

    def __init__(self) -> None:
        """Init."""
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix=(), intents=intents)
        self.tree.on_error = self._on_app_command_error
        self.schedules: ScheduleStore = ScheduleStore()
        self.events: EventStore = EventStore()
        self.timezones: TimezoneStore = TimezoneStore()
        self.pending_confirmations: PendingConfirmationStore = (
            PendingConfirmationStore()
        )

    async def _on_app_command_error(
        self, interaction: Interaction, error: AppCommandError
    ) -> None:
        """Log errors from app command interactions."""
        LOGGER.error(
            "App command error: interaction={}, command={}, error={}",
            interaction.id,
            interaction.command.name if interaction.command else None,
            error,
        )

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

"""Base view with error logging."""

from typing import TYPE_CHECKING
from typing import Any

from discord.ui import Item
from discord.ui import View

from niles.utils.loggers import LOGGER

if TYPE_CHECKING:
    from discord import Interaction


class NilesView(View):
    """Base view with error logging for all Niles UI components."""

    async def on_error(
        self, interaction: Interaction, error: Exception, item: Item[Any], /
    ) -> None:
        """Log view interaction errors and notify the user."""
        LOGGER.error(
            "View interaction failed: interaction={}, item={}, error={}",
            interaction.id,
            item.__class__.__name__,
            error,
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "Something went wrong. Please try again.", ephemeral=True
            )
        else:
            await interaction.followup.send(
                "Something went wrong. Please try again.", ephemeral=True
            )

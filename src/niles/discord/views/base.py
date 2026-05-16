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
        """Log view interaction errors."""
        LOGGER.error(
            "View interaction failed: interaction={}, item={}, error={}",
            interaction.id,
            item.__class__.__name__,
            error,
        )

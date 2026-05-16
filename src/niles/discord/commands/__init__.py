"""Commands."""

from typing import TYPE_CHECKING

from niles.discord.commands.event import event_group
from niles.discord.commands.schedule import schedule_group
from niles.discord.commands.timezone import timezone_group

if TYPE_CHECKING:
    from discord import app_commands


def setup_commands(tree: app_commands.CommandTree) -> None:
    """Register all command groups with the tree."""
    tree.add_command(schedule_group)
    tree.add_command(event_group)
    tree.add_command(timezone_group)

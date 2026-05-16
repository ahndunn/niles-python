"""Commands."""

from discord import app_commands  # noqa: TC002

from niles.discord.commands.event import event_group
from niles.discord.commands.schedule import schedule_group


def setup_commands(tree: app_commands.CommandTree) -> None:
    """Register all command groups with the tree."""
    tree.add_command(schedule_group)
    tree.add_command(event_group)

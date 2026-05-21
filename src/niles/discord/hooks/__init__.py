"""Hooks."""

from niles.discord.hooks.on_disconnect import on_disconnect as on_disconnect
from niles.discord.hooks.on_message import on_message as on_message
from niles.discord.hooks.on_ready import on_ready as on_ready

__all__ = ["on_disconnect", "on_message", "on_ready"]

"""Schedule commands."""

from datetime import UTC
from datetime import datetime

from discord import Interaction
from discord import app_commands

from niles.discord.models import FreeTimeEntry  # noqa: TC001
from niles.discord.stores import get_schedule_store
from niles.discord.views import ClearConfirmView
from niles.discord.views import RemoveSelect
from niles.discord.views import ScheduleAddModal

_MAX_MSG_LEN = 1900

schedule_group = app_commands.Group(
    name="schedule", description="Manage your schedule"
)


@schedule_group.command(name="add", description="Add new free time windows")
async def schedule_add(interaction: Interaction) -> None:
    """Add new free time windows."""
    store = get_schedule_store(interaction)
    if store is None:
        await interaction.response.send_message(
            "Store not available.", ephemeral=True
        )
        return
    modal = ScheduleAddModal(store, interaction.user.id)
    await interaction.response.send_modal(modal)


@schedule_group.command(name="remove", description="Remove a free time window")
async def schedule_remove(interaction: Interaction) -> None:
    """Remove a declared free time window."""
    store = get_schedule_store(interaction)
    if store is None:
        await interaction.response.send_message(
            "Store not available.", ephemeral=True
        )
        return
    now = datetime.now(UTC)
    entries = store.get_user_entries(interaction.user.id)
    future_entries = [
        e for e in entries if any(w.start >= now for w in e.windows)
    ]
    if not future_entries:
        await interaction.response.send_message(
            "No future free time entries to remove.", ephemeral=True
        )
        return
    view = RemoveSelect(store, interaction.user.id, future_entries)
    await interaction.response.send_message(
        "Select an entry to remove:", view=view, ephemeral=True
    )


@schedule_group.command(
    name="clear", description="Clear all future free time windows"
)
async def schedule_clear(interaction: Interaction) -> None:
    """Clear all future free time windows."""
    store = get_schedule_store(interaction)
    if store is None:
        await interaction.response.send_message(
            "Store not available.", ephemeral=True
        )
        return
    now = datetime.now(UTC)
    entries = store.get_user_entries(interaction.user.id)
    future_entries = [
        e for e in entries if any(w.start >= now for w in e.windows)
    ]
    if not future_entries:
        await interaction.response.send_message(
            "No future entries to clear.", ephemeral=True
        )
        return
    view = ClearConfirmView(store, interaction.user.id)
    await interaction.response.send_message(
        f"This will clear {len(future_entries)} future entries. Continue?",
        view=view,
        ephemeral=True,
    )


def _build_heatmap(
    entries: list[FreeTimeEntry], removed_entries: list[FreeTimeEntry]
) -> str:
    """Build a heatmap string from entries."""
    windows: dict[str, list[str]] = {}
    for entry in entries:
        name = f"<@{entry.user_id}>"
        for w in entry.windows:
            key = w.start.strftime("%a %Y-%m-%d %H:%M")
            windows.setdefault(key, []).append(name)

    removed_info: dict[str, list[str]] = {}
    for entry in removed_entries:
        if not entry.removed_reason:
            continue
        for w in entry.windows:
            key = w.start.strftime("%a %Y-%m-%d %H:%M")
            removed_info.setdefault(key, []).append(
                f"<@{entry.user_id}> (removed: {entry.removed_reason})"
            )

    lines: list[str] = []
    for key in sorted(windows):
        users = windows[key]
        lines.append(f"**{key}** - {' '.join(users)}")
        if key in removed_info:
            lines.append(f"  Busy: {'; '.join(removed_info[key])}")

    return "\n".join(lines)


@schedule_group.command(
    name="view", description="View everyone's free time heatmap"
)
async def schedule_view(interaction: Interaction) -> None:
    """Display a heatmap of everyone's free times."""
    store = get_schedule_store(interaction)
    if store is None:
        await interaction.response.send_message(
            "Store not available.", ephemeral=True
        )
        return
    all_entries = store.get_all_entries()
    if not all_entries:
        await interaction.response.send_message(
            "No free time entries found.", ephemeral=True
        )
        return

    removed = store.get_removed_entries()
    msg = _build_heatmap(all_entries, removed)

    if len(msg) > _MAX_MSG_LEN:
        msg = msg[:_MAX_MSG_LEN] + "\n..."

    await interaction.response.send_message(
        f"**Free Time Overview:**\n{msg}", ephemeral=True
    )

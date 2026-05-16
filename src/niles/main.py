"""Main."""

import asyncio
import signal

from niles.configs.settings import Settings
from niles.discord.client import NilesClient
from niles.utils.loggers import LOGGER


async def main() -> None:
    """Entrypoint."""
    settings = Settings()
    client = NilesClient()

    async def _shutdown() -> None:
        LOGGER.info("Shutting down...")
        await client.close()
        await LOGGER.complete()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(_shutdown()))

    try:
        await client.start(settings.DISCORD_TOKEN)
    except Exception:
        LOGGER.exception("Unhandled exception")
        await LOGGER.complete()
        raise
    finally:
        await LOGGER.complete()

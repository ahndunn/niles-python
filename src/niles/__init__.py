"""Niles."""

import asyncio

from niles.main import main as async_main


def main() -> None:
    """Entrypoint."""
    asyncio.run(async_main())

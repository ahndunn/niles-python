"""Main."""

from niles.states import State
from niles.utils.loggers import LOGGER


def _throw() -> None:
    msg = "Error!!!"
    raise ValueError(msg)


async def main() -> None:
    """Entrypoint."""
    try:
        _ = State()
        _throw()
    except BaseException:
        LOGGER.exception("Unhandled exception")
        await LOGGER.complete()
        raise

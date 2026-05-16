"""Loggers."""

import sys
from datetime import UTC
from datetime import time
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Final
from typing import Literal
from typing import final

from loguru import logger as _logger
from pydantic import Field
from pydantic_settings import BaseSettings

if TYPE_CHECKING:
    from loguru import Logger as _Logger


@final
class _LoggerSettings(BaseSettings):
    LEVEL: Literal["DEBUG", "WARNING", "INFO"] = Field(init=False)
    DIR: Path = Field(default_factory=lambda: Path.cwd().joinpath("logs"))

    model_config = {"case_sensitive": True, "env_prefix": "LOG_"}


_LOGGER_SETTINGS: Final[_LoggerSettings] = _LoggerSettings()


_logger.remove()
_logger.add(
    sys.stdout,
    level=_LOGGER_SETTINGS.LEVEL,
    enqueue=True,
    colorize=True,
    serialize=False,
    diagnose=False,
    backtrace=True,
)
_logger.add(
    _LOGGER_SETTINGS.DIR.joinpath("{time:YYYY_MM_DD!UTC}"),
    level=_LOGGER_SETTINGS.LEVEL,
    enqueue=True,
    colorize=True,
    serialize=False,
    diagnose=False,
    backtrace=True,
    rotation=time(0, 0, 0, 0, UTC),
)


LOGGER: Final[_Logger] = _logger

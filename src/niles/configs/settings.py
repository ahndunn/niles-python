"""Settings."""

from typing import final

from pydantic.fields import Field
from pydantic_settings import BaseSettings


@final
class Settings(BaseSettings):
    """Settings."""

    DISCORD_TOKEN: str = Field(init=False)
    model_config = {"case_sensitive": True}

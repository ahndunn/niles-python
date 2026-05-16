"""States."""

from dataclasses import dataclass
from dataclasses import field

from niles.configs.settings import Settings


@dataclass(frozen=True, slots=True)
class State:
    """State."""

    settings: Settings = field(default_factory=Settings)

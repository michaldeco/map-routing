"""Paths and settings, overridable through environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path

from map_routing import __version__

DEFAULT_USER_AGENT = f"map-routing/{__version__}"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    user_agent: str

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def areas_dir(self) -> Path:
        return self.data_dir / "areas"

    @property
    def scenarios_dir(self) -> Path:
        return self.data_dir / "scenarios"

    def area_dir(self, slug: str) -> Path:
        return self.areas_dir / slug


def load_settings() -> Settings:
    """Read settings from the environment.

    MAP_ROUTING_DATA_DIR: data folder (default: ./data).
    MAP_ROUTING_USER_AGENT: User-Agent sent to external services. The default is
    generic and contains no personal details.
    """
    return Settings(
        data_dir=Path(os.environ.get("MAP_ROUTING_DATA_DIR", "data")),
        user_agent=os.environ.get("MAP_ROUTING_USER_AGENT", DEFAULT_USER_AGENT),
    )

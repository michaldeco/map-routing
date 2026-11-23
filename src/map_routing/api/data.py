"""Data access for the API: areas, imputed buildings and scenarios on disk.

Names coming from URLs are validated before they touch the file system, so a
request can never read outside the data folder.
"""

import json
import re
import threading
from pathlib import Path

import geopandas as gpd

from map_routing.area.model import SLUG_RE, Area
from map_routing.scenario.io import read_scenario
from map_routing.scenario.schema import Scenario
from map_routing.settings import Settings

# Scenario folder names, e.g. "thessaloniki-full-high-s1".
SCENARIO_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class NotFound(LookupError):
    pass


class DataStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._buildings: dict[str, tuple[float, gpd.GeoDataFrame]] = {}
        self._lock = threading.Lock()

    # Areas

    def area_slugs(self) -> list[str]:
        root = self.settings.areas_dir
        if not root.is_dir():
            return []
        return sorted(
            d.name for d in root.iterdir() if (d / "area.json").is_file() and SLUG_RE.match(d.name)
        )

    def area(self, slug: str) -> Area:
        if not SLUG_RE.match(slug) or slug not in self.area_slugs():
            raise NotFound(f"area {slug!r} not found")
        return Area.load(self.settings.area_dir(slug))

    def has_buildings(self, slug: str) -> bool:
        return (self.settings.area_dir(slug) / "buildings.parquet").is_file()

    def buildings(self, slug: str) -> gpd.GeoDataFrame:
        """Imputed buildings of an area, cached in memory; reloaded when the file changes
        (e.g. after `buildings impute` ran again)."""
        self.area(slug)
        path = self.settings.area_dir(slug) / "buildings.parquet"
        if not path.is_file():
            raise NotFound(f"area {slug!r} has no imputed buildings; run `buildings impute`")
        mtime = path.stat().st_mtime
        with self._lock:
            cached = self._buildings.get(slug)
            if cached is None or cached[0] != mtime:
                cached = (mtime, gpd.read_parquet(path))
                self._buildings[slug] = cached
        return cached[1]

    # Scenarios

    def scenario_dirs(self) -> list[Path]:
        root = self.settings.scenarios_dir
        if not root.is_dir():
            return []
        return sorted(
            d
            for d in root.iterdir()
            if (d / "scenario.json").is_file() and SCENARIO_NAME_RE.match(d.name)
        )

    def scenario_meta(self, directory: Path) -> dict:
        return json.loads((directory / "scenario.json").read_text())

    def scenario(self, name: str) -> Scenario:
        if not SCENARIO_NAME_RE.match(name):
            raise NotFound(f"scenario {name!r} not found")
        directory = self.settings.scenarios_dir / name
        if directory not in self.scenario_dirs():
            raise NotFound(f"scenario {name!r} not found")
        return read_scenario(directory)

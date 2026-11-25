"""Data access for the API: areas, imputed buildings and scenarios on disk.

Names coming from URLs are validated before they touch the file system, so a
request can never read outside the data folder.
"""

import json
import re
import threading
from collections.abc import Callable
from pathlib import Path

import geopandas as gpd

from map_routing.area.model import SLUG_RE, Area
from map_routing.scenario.io import read_scenario
from map_routing.scenario.schema import Scenario, ScenarioMeta
from map_routing.settings import Settings

# Scenario folder names, e.g. "thessaloniki-full-high-s1".
SCENARIO_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REGENERATE_HINT = "check its files or generate it again with `scenario generate`"


class NotFound(LookupError):
    pass


class BrokenData(Exception):
    """A file exists but cannot be read or does not pass validation, e.g. it was
    edited by hand, half-written, or produced by an older version of the code."""


def _read[T](what: str, hint: str, read: Callable[[], T]) -> T:
    """Run `read`, turning read and validation errors into `BrokenData` with a hint
    on how to fix it. (Pydantic's ValidationError, json's JSONDecodeError and
    pyarrow's ArrowInvalid are all ValueErrors.)"""
    try:
        return read()
    except (OSError, ValueError) as exc:
        raise BrokenData(f"{what} cannot be read; {hint}. Details: {exc}") from exc


class DataStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._buildings: dict[str, tuple[float, gpd.GeoDataFrame]] = {}
        # One lock per area: loading a large area takes seconds and must not hold up
        # requests for other areas. `_locks_lock` only guards creating these locks.
        self._area_locks: dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()

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
        return _read(
            f"area {slug!r}",
            "define and fetch it again with `area define` and `area fetch`",
            lambda: Area.load(self.settings.area_dir(slug)),
        )

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
        with self._locks_lock:
            lock = self._area_locks.setdefault(slug, threading.Lock())
        with lock:
            cached = self._buildings.get(slug)
            if cached is None or cached[0] != mtime:
                frame = _read(
                    f"imputed buildings of area {slug!r}",
                    "run `buildings impute` again",
                    lambda: gpd.read_parquet(path),
                )
                cached = (mtime, frame)
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

    def scenario_meta(self, directory: Path) -> tuple[ScenarioMeta, dict]:
        """A scenario's validated metadata and the raw file (which also stores the
        number of locations and visits), without reading its CSV."""

        def read() -> tuple[ScenarioMeta, dict]:
            raw = json.loads((directory / "scenario.json").read_text())
            return ScenarioMeta.model_validate(raw), raw

        return _read(f"scenario {directory.name!r}", REGENERATE_HINT, read)

    def scenario(self, name: str) -> Scenario:
        if not SCENARIO_NAME_RE.match(name):
            raise NotFound(f"scenario {name!r} not found")
        directory = self.settings.scenarios_dir / name
        if directory not in self.scenario_dirs():
            raise NotFound(f"scenario {name!r} not found")
        return _read(f"scenario {name!r}", REGENERATE_HINT, lambda: read_scenario(directory))

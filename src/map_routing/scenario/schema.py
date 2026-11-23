"""The scenario format: the engine's only input, whatever produced it.

A scenario describes one planning situation: which locations need visits, how
often and for how long (the demand), on which weekdays visits are allowed, and the
workforce settings (e.g. shift length). It contains no decisions; the engine
(clustering, weekday assignment, routing, workforce calculation) turns a scenario
into a weekly plan.

Intended usage:
- Synthetic scenarios (`map-routing scenario generate`) for development, tests,
  benchmarks and the demo, in several sizes and loads, e.g.
  `thessaloniki-full-high-s1`.
- Later, a client's real customer list (user import), producing the same format.
- What-if comparisons: variants of a scenario (more visits, longer shifts, added
  buildings) planned and compared side by side; reoptimization starts from a
  previous plan and a changed scenario.

On disk, a scenario is a folder with `scenario.json` (metadata, source, seed,
workforce settings) and `buildings.csv` (one row per location with its visit
demand). Every source passes the same validation.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class Location(BaseModel):
    id: str = Field(min_length=1)
    osm_id: str | None = None
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    address: str | None = None
    floors: float | None = Field(default=None, ge=1)
    footprint_m2: float | None = Field(default=None, gt=0)
    floors_source: str | None = None
    address_source: str | None = None
    visits_per_week: int = Field(ge=1, le=7)
    duration_min: float = Field(ge=5, le=240)
    allowed_days: tuple[str, ...] = WEEKDAYS
    # Synthetic scenarios only: which dense area (area1, area2, ...) or "outlier" the
    # location was drawn from. For checking and maps; the engine ignores it.
    component: str | None = None

    @field_validator("allowed_days", mode="before")
    @classmethod
    def _parse_days(cls, v: object) -> object:
        if isinstance(v, str):
            return tuple(v.split())
        return v

    @field_validator("allowed_days")
    @classmethod
    def _known_days(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        unknown = set(v) - set(WEEKDAYS)
        if unknown:
            raise ValueError(f"unknown weekdays {sorted(unknown)}; use {' '.join(WEEKDAYS)}")
        if len(set(v)) != len(v):
            raise ValueError("allowed_days contains duplicates")
        return tuple(d for d in WEEKDAYS if d in v)  # canonical order

    @model_validator(mode="after")
    def _enough_days(self) -> Location:
        if len(self.allowed_days) < self.visits_per_week:
            raise ValueError(
                f"{self.id}: {self.visits_per_week} visits per week but only "
                f"{len(self.allowed_days)} allowed days"
            )
        return self


class Workforce(BaseModel):
    shift_min: float = Field(default=480, gt=0, le=24 * 60)
    # Where a cleaner's day starts: at the first visit (no travel counted before it)
    # or at given start points (added in a later milestone).
    start: Literal["first_visit"] = "first_visit"


class ScenarioMeta(BaseModel):
    name: str
    area_slug: str
    area_data_date: str | None = None
    source: Literal["synthetic", "import"]
    created: datetime
    seed: int | None = None
    parameters: dict = Field(default_factory=dict)
    workforce: Workforce = Field(default_factory=Workforce)


class Scenario(BaseModel):
    meta: ScenarioMeta
    locations: list[Location]

    @model_validator(mode="after")
    def _unique_ids(self) -> Scenario:
        seen, dupes = set(), set()
        for loc in self.locations:
            (dupes if loc.id in seen else seen).add(loc.id)
        if dupes:
            raise ValueError(f"duplicate location ids: {sorted(dupes)[:5]}")
        if not self.locations:
            raise ValueError("scenario has no locations")
        return self

    @property
    def visits_per_week(self) -> int:
        return sum(loc.visits_per_week for loc in self.locations)


def outside(scenario: Scenario, boundary: BaseGeometry) -> list[str]:
    """Ids of locations outside the area boundary (a validation check that needs the area)."""
    return [loc.id for loc in scenario.locations if not boundary.covers(Point(loc.lon, loc.lat))]

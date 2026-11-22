"""The instance format: the engine's only input, whatever produced it.

An instance is a folder with `instance.json` (metadata, workforce settings) and
`buildings.csv` (one row per location with its visit demand). Synthetic data and
user imports produce the same format and pass the same validation.
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


class InstanceMeta(BaseModel):
    name: str
    area_slug: str
    area_data_date: str | None = None
    source: Literal["synthetic", "import"]
    created: datetime
    seed: int | None = None
    parameters: dict = Field(default_factory=dict)
    workforce: Workforce = Field(default_factory=Workforce)


class Instance(BaseModel):
    meta: InstanceMeta
    locations: list[Location]

    @model_validator(mode="after")
    def _unique_ids(self) -> Instance:
        seen, dupes = set(), set()
        for loc in self.locations:
            (dupes if loc.id in seen else seen).add(loc.id)
        if dupes:
            raise ValueError(f"duplicate location ids: {sorted(dupes)[:5]}")
        if not self.locations:
            raise ValueError("instance has no locations")
        return self

    @property
    def visits_per_week(self) -> int:
        return sum(loc.visits_per_week for loc in self.locations)


def outside(instance: Instance, boundary: BaseGeometry) -> list[str]:
    """Ids of locations outside the area boundary (a validation check that needs the area)."""
    return [loc.id for loc in instance.locations if not boundary.covers(Point(loc.lon, loc.lat))]

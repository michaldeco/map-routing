"""An area: a named boundary on the map, stored as data/areas/<slug>/area.json."""

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from shapely.geometry import box, mapping, shape
from shapely.geometry.base import BaseGeometry

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class AreaDefinition(BaseModel):
    """How the boundary was obtained, so it can be reproduced."""

    kind: Literal["bbox", "polygon", "place"]
    value: str  # "W,S,E,N", a file name, or the place query
    source: str | None = None  # e.g. "nominatim:relation/123" for places


class SourceExtract(BaseModel):
    id: str
    name: str
    url: str


class Area(BaseModel):
    slug: str
    name: str
    definition: AreaDefinition
    boundary: dict = Field(description="GeoJSON geometry in WGS84 (Polygon or MultiPolygon)")
    source_extract: SourceExtract | None = None
    data_date: str | None = None  # OSM data timestamp of the source extract

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG_RE.match(v):
            raise ValueError("slug must be lowercase letters, digits and single hyphens")
        return v

    @field_validator("boundary")
    @classmethod
    def _boundary(cls, v: dict) -> dict:
        geom = shape(v)
        if geom.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError(f"boundary must be a polygon, got {geom.geom_type}")
        if not geom.is_valid or geom.is_empty:
            raise ValueError("boundary polygon is empty or invalid")
        return json.loads(json.dumps(mapping(geom)))  # plain lists, as after a JSON round trip

    @property
    def geometry(self) -> BaseGeometry:
        return shape(self.boundary)

    def save(self, area_dir: Path) -> Path:
        area_dir.mkdir(parents=True, exist_ok=True)
        path = area_dir / "area.json"
        path.write_text(self.model_dump_json(indent=2) + "\n")
        return path

    @classmethod
    def load(cls, area_dir: Path) -> Area:
        path = area_dir / "area.json"
        if not path.exists():
            raise FileNotFoundError(f"{path} not found; run `map-routing area define` first")
        return cls.model_validate_json(path.read_text())


def parse_bbox(text: str) -> BaseGeometry:
    """'W,S,E,N' in degrees -> polygon."""
    try:
        w, s, e, n = (float(x) for x in text.split(","))
    except ValueError as exc:
        raise ValueError(f"bbox must be W,S,E,N numbers, got {text!r}") from exc
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError(f"bbox out of range or not W<E, S<N: {text!r}")
    return box(w, s, e, n)


def read_polygon_file(path: Path) -> BaseGeometry:
    """First polygon geometry from a GeoJSON file (geometry, Feature or FeatureCollection)."""
    data = json.loads(path.read_text())
    if data.get("type") == "FeatureCollection":
        data = data["features"][0]
    if data.get("type") == "Feature":
        data = data["geometry"]
    return shape(data)


def make_area(slug: str, name: str, definition: AreaDefinition, geometry: BaseGeometry) -> Area:
    return Area(slug=slug, name=name, definition=definition, boundary=mapping(geometry))

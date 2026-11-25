"""API response models. They define the JSON the web app receives; the frontend's
TypeScript types are generated from the OpenAPI description built from them.

They are a separate layer from the core models (Area, Scenario, Location,
DenseArea, ...): the API depends on the core, never the other way round, and the
contract with the frontend changes only when these models change.

Naming rule (enforced by a test): never reuse a core model's name. Resources are
`...Summary` (list entries) or `...Detail` (one resource); GeoJSON shapes are
`...Feature`, `...Properties`, `...Collection`; API-only concepts keep their names.

Spatial data is GeoJSON (RFC 7946): longitude/latitude in WGS84 degrees.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

ColourBy = Literal["residential", "reason", "floors-source", "floors"]


class Bounds(BaseModel):
    west: float
    south: float
    east: float
    north: float


class AreaSummary(BaseModel):
    slug: str
    name: str
    data_date: str | None = Field(description="OSM data timestamp of the source extract")
    bounds: Bounds
    has_buildings: bool = Field(description="Imputed buildings exist (buildings impute ran)")


Position = tuple[float, float]  # [longitude, latitude]


class PolygonGeometry(BaseModel):
    type: Literal["Polygon"]
    coordinates: list[list[Position]] = Field(description="Outer ring, then holes")


class MultiPolygonGeometry(BaseModel):
    type: Literal["MultiPolygon"]
    coordinates: list[list[list[Position]]]


class AreaDetail(AreaSummary):
    boundary: Annotated[PolygonGeometry | MultiPolygonGeometry, Field(discriminator="type")] = (
        Field(description="Area boundary as a GeoJSON geometry")
    )


class LegendItem(BaseModel):
    value: str = Field(description="Category as it appears in feature properties")
    count: int
    description: str = Field(description="One plain-language line explaining the category")


class Legend(BaseModel):
    title: str
    subtitle: str = Field(description="What the colours (and sizes) mean")
    items: list[LegendItem] = Field(description="In display order")
    footer: str = ""
    note: str = Field("", description="A warning to show, e.g. for outdated data")


class PointGeometry(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float] = Field(description="[longitude, latitude]")


class BuildingProperties(BaseModel):
    osm_id: str
    building: str | None
    residential: bool
    reason: str | None
    floors: float | None
    floors_source: str | None
    footprint_m2: float | None
    address: str | None
    category: str = Field(description="Legend category for the requested colouring")


class BuildingFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: PointGeometry
    properties: BuildingProperties


class BuildingCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[BuildingFeature]
    colour_by: ColourBy
    total: int = Field(description="Buildings matching the filter, before sampling")
    shown: int
    sampled: bool
    seed: int
    legend: Legend


class ScenarioSummary(BaseModel):
    name: str
    area_slug: str
    source: str
    created: datetime
    seed: int | None
    size: str | None
    layout: str | None
    load: str | None
    locations: int
    visits_per_week: int


class DenseAreaDetail(BaseModel):
    group: str = Field(description="Dense area, e.g. area1 (matches the locations' group)")
    lon: float
    lat: float
    sigma_m: float = Field(description="Typical spread in metres")
    weight: float = Field(description="Intended share of the scenario's buildings")


class LocationProperties(BaseModel):
    id: str
    group: str = Field(description="Dense area (area1, ...), outlier, or location")
    osm_id: str | None
    address: str | None
    floors: float | None
    floors_source: str | None
    footprint_m2: float | None
    visits_per_week: int
    duration_min: float
    allowed_days: list[str]


class LocationFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: PointGeometry
    properties: LocationProperties


class ScenarioDetail(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    summary: ScenarioSummary
    features: list[LocationFeature]
    dense_areas: list[DenseAreaDetail]
    legend: Legend

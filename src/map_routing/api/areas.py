"""Area endpoints: areas, their boundaries and imputed buildings."""

import logging
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Query

from map_routing import legends
from map_routing.api.data import BrokenData, DataStore
from map_routing.api.dependencies import Store
from map_routing.api.models import (
    AreaDetail,
    AreaSummary,
    Bounds,
    BuildingCollection,
    BuildingFeature,
    BuildingProperties,
    ColourBy,
    Legend,
    LegendItem,
    PointGeometry,
)
from map_routing.area.model import Area

MAX_SAMPLE = 50_000  # more points than this make the browser slow; use `all` deliberately
MAX_SEED = 2**32 - 1  # numpy's random generators accept seeds 0 .. 2**32 - 1

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/areas", tags=["areas"])


@router.get("")
def list_areas(store: Store) -> list[AreaSummary]:
    """Every readable area; a broken one is skipped (and logged) so the others
    still show."""
    summaries = []
    for slug in store.area_slugs():
        try:
            summaries.append(_area_summary(store, store.area(slug)))
        except BrokenData as exc:
            log.warning("skipping %s", exc)
    return summaries


@router.get("/{slug}")
def get_area(slug: str, store: Store) -> AreaDetail:
    area = store.area(slug)
    return AreaDetail(**_area_summary(store, area).model_dump(), boundary=area.boundary)


@router.get("/{slug}/buildings")
def get_buildings(
    slug: str,
    store: Store,
    colour_by: ColourBy = "reason",
    sample: Annotated[int, Query(ge=1, le=MAX_SAMPLE)] = 5000,
    seed: Annotated[int, Query(ge=0, le=MAX_SEED)] = 0,
    residential_only: bool = False,
    all: Annotated[bool, Query(description="Every building, no sampling")] = False,  # noqa: A002
) -> BuildingCollection:
    """Imputed buildings as points, each with its legend category for `colour_by`."""
    area = store.area(slug)
    b = store.buildings(slug)
    if residential_only:
        b = b[b.residential]
    shown, total = legends.sample_buildings(b, None if all else sample, seed)
    values = legends.group_rare(legends.categories(shown, colour_by), colour_by)
    features = [
        BuildingFeature(
            geometry=PointGeometry(coordinates=(row.lon, row.lat)),
            properties=BuildingProperties(
                osm_id=row.osm_id,
                building=_text(row.building),
                residential=bool(row.residential),
                reason=_text(row.residential_reason),
                floors=_number(row.floors),
                floors_source=_text(row.floors_source),
                footprint_m2=_number(row.footprint_m2),
                address=_text(row.address),
                category=category,
            ),
        )
        for row, category in zip(shown.itertuples(), values, strict=True)
    ]
    what = "residential buildings" if residential_only else "buildings"
    sampled = len(shown) < total
    legend = Legend(
        title=f"{area.name}: {len(shown):,} of {total:,} {what}"
        + (" (random sample)" if sampled else ""),
        subtitle=legends.COLOUR_BY_SUBTITLE[colour_by],
        items=[
            LegendItem(value=v, count=n, description=legends.explain(colour_by, v))
            for v, n in legends.ordered_counts(values, colour_by)
        ],
        footer=legends.BUILDINGS_FOOTER,
    )
    return BuildingCollection(
        features=features,
        colour_by=colour_by,
        total=total,
        shown=len(shown),
        sampled=sampled,
        seed=seed,
        legend=legend,
    )


def _area_summary(store: DataStore, area: Area) -> AreaSummary:
    west, south, east, north = area.geometry.bounds
    return AreaSummary(
        slug=area.slug,
        name=area.name,
        data_date=area.data_date,
        bounds=Bounds(west=west, south=south, east=east, north=north),
        has_buildings=store.has_buildings(area.slug),
    )


def _text(value: object) -> str | None:
    """A text cell, or None if missing (None, NaN, pd.NA, ...)."""
    return None if pd.isna(value) else str(value)


def _number(value: object) -> float | None:
    """A numeric cell, or None if missing (None, NaN, pd.NA, ...)."""
    return None if pd.isna(value) else float(value)

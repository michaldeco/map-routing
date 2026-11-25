"""FastAPI application: read-only endpoints for the web app.

Run it with `map-routing api` (development) or `map-routing ui` (later, with the
web app). It binds to 127.0.0.1 only; there is no authentication.
"""

import logging
from typing import Annotated

import pandas as pd
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from map_routing import __version__, legends
from map_routing.api.data import BrokenData, DataStore, NotFound
from map_routing.api.models import (
    AreaDetail,
    AreaSummary,
    Bounds,
    BuildingCollection,
    BuildingFeature,
    BuildingProperties,
    ColourBy,
    DenseAreaDetail,
    Legend,
    LegendItem,
    LocationFeature,
    LocationProperties,
    PointGeometry,
    ScenarioDetail,
    ScenarioSummary,
)
from map_routing.area.model import Area
from map_routing.scenario.schema import ScenarioMeta
from map_routing.settings import Settings, load_settings

MAX_SAMPLE = 50_000  # more points than this make the browser slow; use `all` deliberately
MAX_SEED = 2**32 - 1  # numpy's random generators accept seeds 0 .. 2**32 - 1

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    store = DataStore(settings or load_settings())
    app = FastAPI(
        title="map-routing",
        version=__version__,
        summary="Read-only API for the map-routing web app.",
    )

    @app.exception_handler(NotFound)
    async def not_found(_: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(BrokenData)
    async def broken_data(_: Request, exc: BrokenData) -> JSONResponse:
        # A server-side data problem (500), but with a message that says what to fix.
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/areas")
    def list_areas() -> list[AreaSummary]:
        """Every readable area; a broken one is skipped (and logged) so the others
        still show."""
        summaries = []
        for slug in store.area_slugs():
            try:
                summaries.append(_area_summary(store, store.area(slug)))
            except BrokenData as exc:
                log.warning("skipping %s", exc)
        return summaries

    @app.get("/api/areas/{slug}")
    def get_area(slug: str) -> AreaDetail:
        area = store.area(slug)
        return AreaDetail(**_area_summary(store, area).model_dump(), boundary=area.boundary)

    @app.get("/api/areas/{slug}/buildings")
    def get_buildings(
        slug: str,
        colour_by: ColourBy = "reason",
        sample: Annotated[int, Query(ge=1, le=MAX_SAMPLE)] = 5000,
        seed: Annotated[int, Query(ge=0, le=MAX_SEED)] = 0,
        residential_only: bool = False,
        all: Annotated[
            bool, Query(description="Every building, no sampling")
        ] = False,  # noqa: A002
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

    @app.get("/api/scenarios")
    def list_scenarios(
        area: Annotated[str | None, Query(description="Only this area")] = None,
    ) -> list[ScenarioSummary]:
        """Every readable scenario; a broken one is skipped (and logged) so the others
        still show."""
        summaries = []
        for directory in store.scenario_dirs():
            try:
                meta, raw = store.scenario_meta(directory)
            except BrokenData as exc:
                log.warning("skipping %s", exc)
                continue
            if area is None or meta.area_slug == area:
                summaries.append(
                    _scenario_summary(meta, raw.get("locations", 0), raw.get("visits_per_week", 0))
                )
        return summaries

    @app.get("/api/scenarios/{name}")
    def get_scenario(name: str) -> ScenarioDetail:
        """A scenario's locations as points, with its dense-area centres and legend."""
        scenario = store.scenario(name)
        dense_areas = legends.dense_areas(scenario)
        groups = legends.scenario_groups(scenario)
        features = [
            LocationFeature(
                geometry=PointGeometry(coordinates=(loc.lon, loc.lat)),
                properties=LocationProperties(
                    id=loc.id,
                    group=loc.component or "location",
                    osm_id=loc.osm_id,
                    address=loc.address,
                    floors=loc.floors,
                    floors_source=loc.floors_source,
                    footprint_m2=loc.footprint_m2,
                    visits_per_week=loc.visits_per_week,
                    duration_min=loc.duration_min,
                    allowed_days=list(loc.allowed_days),
                ),
            )
            for loc in scenario.locations
        ]
        legend = Legend(
            title=(
                f"{scenario.meta.name}: {len(scenario.locations):,} locations, "
                f"{scenario.visits_per_week:,} visits/week"
            ),
            subtitle=legends.SCENARIO_SUBTITLE,
            items=[
                LegendItem(value=g, count=n, description=legends.describe_group(g, dense_areas))
                for g, n in groups
            ],
            footer=legends.SCENARIO_FOOTER,
            note=legends.MISSING_COMPONENTS_NOTE if legends.missing_components(scenario) else "",
        )
        return ScenarioDetail(
            summary=_scenario_summary(
                scenario.meta, len(scenario.locations), scenario.visits_per_week
            ),
            features=features,
            dense_areas=[
                DenseAreaDetail(
                    group=d.component, lon=d.lon, lat=d.lat, sigma_m=d.sigma_m, weight=d.weight
                )
                for d in dense_areas
            ],
            legend=legend,
        )

    return app


def app_factory():
    """Entry point for uvicorn (`--factory`), using settings from the environment."""
    return create_app(load_settings())


def _area_summary(store: DataStore, area: Area) -> AreaSummary:
    west, south, east, north = area.geometry.bounds
    return AreaSummary(
        slug=area.slug,
        name=area.name,
        data_date=area.data_date,
        bounds=Bounds(west=west, south=south, east=east, north=north),
        has_buildings=store.has_buildings(area.slug),
    )


def _scenario_summary(meta: ScenarioMeta, locations: int, visits: int) -> ScenarioSummary:
    synthetic = meta.synthetic
    return ScenarioSummary(
        name=meta.name,
        area_slug=meta.area_slug,
        source=meta.source,
        created=meta.created,
        seed=meta.seed,
        size=synthetic.size if synthetic else None,
        layout=synthetic.layout if synthetic else None,
        load=synthetic.load if synthetic else None,
        locations=locations,
        visits_per_week=visits,
    )


def _text(value: object) -> str | None:
    """A text cell, or None if missing (None, NaN, pd.NA, ...)."""
    return None if pd.isna(value) else str(value)


def _number(value: object) -> float | None:
    """A numeric cell, or None if missing (None, NaN, pd.NA, ...)."""
    return None if pd.isna(value) else float(value)

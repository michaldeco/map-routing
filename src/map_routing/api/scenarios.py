"""Scenario endpoints: summaries and locations with their legend."""

import logging
from typing import Annotated

from fastapi import APIRouter, Query

from map_routing import legends
from map_routing.api.data import BrokenData
from map_routing.api.dependencies import Store
from map_routing.api.models import (
    DenseAreaDetail,
    Legend,
    LegendItem,
    LocationFeature,
    LocationProperties,
    PointGeometry,
    ScenarioDetail,
    ScenarioSummary,
)
from map_routing.scenario.schema import ScenarioMeta

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


@router.get("")
def list_scenarios(
    store: Store,
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


@router.get("/{name}")
def get_scenario(name: str, store: Store) -> ScenarioDetail:
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
        summary=_scenario_summary(scenario.meta, len(scenario.locations), scenario.visits_per_week),
        features=features,
        dense_areas=[
            DenseAreaDetail(
                group=d.component, lon=d.lon, lat=d.lat, sigma_m=d.sigma_m, weight=d.weight
            )
            for d in dense_areas
        ],
        legend=legend,
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

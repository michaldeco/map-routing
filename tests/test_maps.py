import threading
import urllib.request
from datetime import UTC, datetime

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from map_routing.area.model import AreaDefinition, make_area
from map_routing.geo import WGS84
from map_routing.maps import (
    OTHER_COLOUR,
    PALETTE,
    buildings_map,
    category_colours,
    make_server,
    sample_buildings,
    scenario_map,
)
from map_routing.scenario.schema import Location, Scenario, ScenarioMeta

AREA = make_area(
    "t", "Testville", AreaDefinition(kind="bbox", value="x"), box(22.9, 40.6, 23.0, 40.7)
)


def scenario():
    locs = [
        Location(
            id=f"b{i}",
            lat=40.62 + i * 1e-4,
            lon=22.95,
            visits_per_week=1 + i % 3,
            duration_min=30,
            component=["area1", "area2", "outlier"][i % 3],
        )
        for i in range(9)
    ]
    meta = ScenarioMeta(
        name="t-small-s1",
        area_slug="t",
        source="synthetic",
        created=datetime(2026, 11, 23, tzinfo=UTC),
        parameters={
            "centres": [
                {"lon": 22.95, "lat": 40.62, "sigma_m": 700, "weight": 0.5},
                {"lon": 22.96, "lat": 40.63, "sigma_m": 500, "weight": 0.3},
            ]
        },
    )
    return Scenario(meta=meta, locations=locs)


def buildings(n=20):
    rng = np.random.default_rng(0)
    lon, lat = rng.uniform(22.91, 22.99, n), rng.uniform(40.61, 40.69, n)
    df = pd.DataFrame(
        {
            "osm_id": [f"w{i}" for i in range(n)],
            "building": "yes",
            "lon": lon,
            "lat": lat,
            "residential": [i % 2 == 0 for i in range(n)],
            "residential_reason": [
                "footprint ok" if i % 2 == 0 else "footprint<150" for i in range(n)
            ],
            "footprint_m2": 200.0,
            "floors": [float(1 + i % 12) for i in range(n)],
            "floors_source": ["osm", "neighbours_300m"] * (n // 2),
            "address": None,
        }
    )
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(lon, lat), crs=WGS84)


def test_scenario_map_layers_and_legend():
    html = scenario_map(scenario(), AREA).get_root().render()
    for text in (
        "area1 (3)",
        "area2 (3)",
        "outlier (3)",
        "Dense area centres",
        "t-small-s1: 9 locations, 18 visits/week",
        "openstreetmap",
    ):
        assert text in html
    assert html.count("L.circle(") == 4  # 1σ and 2σ for two centres


def test_scenario_map_without_components():
    s = scenario()
    for loc in s.locations:
        loc.component = None
    html = scenario_map(s, AREA).get_root().render()
    assert "location (9)" in html


def test_category_colours_top_and_other():
    cats = ["a"] * 5 + ["b"] * 3 + ["c"]
    colours = category_colours(cats, top=2)
    assert colours == {"a": PALETTE[0], "b": PALETTE[1], "c": OTHER_COLOUR}


def test_sample_is_deterministic_and_bounded():
    b = buildings(20)
    s1, total = sample_buildings(b, 5, seed=1)
    s2, _ = sample_buildings(b, 5, seed=1)
    assert total == 20 and len(s1) == 5 and s1.osm_id.tolist() == s2.osm_id.tolist()
    all_, _ = sample_buildings(b, None, seed=1)
    assert len(all_) == 20
    assert len(sample_buildings(b, 100, seed=1)[0]) == 20


@pytest.mark.parametrize("colour_by", ["residential", "reason", "floors-source", "floors"])
def test_buildings_map_colourings(colour_by):
    html = buildings_map(buildings(20), AREA, colour_by=colour_by, sample=5).get_root().render()
    assert "5 of 20 buildings (random sample)" in html
    assert html.count("L.circleMarker(") == 5


def test_buildings_map_residential_only_and_all():
    html = (
        buildings_map(buildings(20), AREA, sample=None, residential_only=True).get_root().render()
    )
    assert "10 of 10 residential buildings, by reason" in html
    with pytest.raises(ValueError):
        buildings_map(buildings(4), AREA, colour_by="height")


def test_view_server_serves_the_map(tmp_path):
    page = tmp_path / "my map.html"
    page.write_text("<html>hello map</html>")
    server, url = make_server(page, port=0)
    with server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        assert url.startswith("http://127.0.0.1:") and url.endswith("/my%20map.html")
        assert urllib.request.urlopen(url, timeout=5).read() == b"<html>hello map</html>"
        server.shutdown()


def test_floor_bands_in_natural_order():
    html = buildings_map(buildings(20), AREA, colour_by="floors", sample=None).get_root().render()
    positions = [html.index(band) for band in ("1–2 floors", "3–4 floors", "10+ floors")]
    assert positions == sorted(positions)


def test_centre_circles_do_not_block_building_tooltips():
    html = scenario_map(scenario(), AREA).get_root().render()
    circles = [part for part in html.split("L.circle(")[1:]]
    assert len(circles) == 4 and all('"interactive": false' in c[:600] for c in circles)
    # drawn before the buildings, so buildings are on top
    assert html.index("L.circle(") < html.index("L.circleMarker(")

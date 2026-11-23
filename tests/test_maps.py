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
        "Dense area centres and spread",
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
    assert "10 of 10 residential buildings" in html and "why the building counts" in html
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


def test_osm_text_is_escaped():
    """OSM values are user-editable; they must not become HTML on the map."""
    s = scenario()
    s.locations[0].address = "<img src=x onerror=alert(1)>"
    page = scenario_map(s, AREA).get_root().render()
    assert "<img src=x" not in page and "&lt;img src=x" in page
    b = buildings(4)
    b["building"] = "<b>bold</b>"
    b["residential_reason"] = "building=<script>"
    page = buildings_map(b, AREA, sample=None).get_root().render()
    assert "building=&lt;script&gt;" in page and "<b>bold</b>" not in page


def test_busy_port_falls_back_to_a_free_one(tmp_path):
    import socket

    page = tmp_path / "m.html"
    page.write_text("x")
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        server, url = make_server(page, port=taken)
        with server:
            assert server.server_port != taken and f":{server.server_port}/" in url


def test_unknown_floors_have_their_own_legend_row():
    b = buildings(10)
    b.loc[:4, "floors"] = np.nan
    page = buildings_map(b, AREA, colour_by="floors", sample=None).get_root().render()
    assert "<b>unknown</b> (5)" in page and "<b>other</b>" not in page


def test_many_dense_areas_sorted_numerically_with_distinct_colours():
    from map_routing.maps import group_colour

    s = scenario()
    s.locations = [
        Location(
            id=f"b{i}",
            lat=40.62,
            lon=22.95,
            visits_per_week=1,
            duration_min=30,
            component=f"area{i + 1}",
        )
        for i in range(12)
    ]
    page = scenario_map(s, AREA).get_root().render()
    order = [page.index(f"area{k} (1)") for k in (1, 2, 9, 10, 11)]
    assert order == sorted(order)
    assert len({group_colour(i) for i in range(12)}) == 12


def test_old_scenarios_get_a_note_instead_of_silent_grey():
    from map_routing.maps import missing_components

    s = scenario()
    for loc in s.locations:
        loc.component = None
    assert missing_components(s)
    assert "regenerate it" in scenario_map(s, AREA).get_root().render()
    assert not missing_components(scenario())


@pytest.mark.parametrize(
    "floors,band", [(2.4, "1–2 floors"), (2.6, "3–4 floors"), (9.5, "10+ floors")]
)
def test_floor_band_rounds(floors, band):
    from map_routing.maps import _floor_band

    assert _floor_band(floors) == band


def test_cli_all_ignores_sample(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from map_routing.cli import app

    monkeypatch.setenv("MAP_ROUTING_DATA_DIR", str(tmp_path))
    area_dir = tmp_path / "areas" / "t"
    AREA.save(area_dir)
    buildings(6).to_parquet(area_dir / "buildings.parquet")
    result = CliRunner().invoke(app, ["buildings", "map", "t", "--all", "--sample", "0"])
    assert result.exit_code == 0, result.output
    assert (area_dir / "buildings-reason.html").exists()


@pytest.mark.parametrize(
    "colour_by,value,expected",
    [
        ("floors-source", "neighbours_300m", "within 300 m"),
        ("floors-source", "neighbours_1000m", "within 1000 m"),
        ("floors-source", "area_median", "area's typical value"),
        ("floors-source", "osm", "tagged in OpenStreetMap"),
        ("reason", "building=apartments", "names its type: apartments"),
        ("reason", "amenity=place_of_worship", "used as: place of worship"),
        ("reason", "footprint<150", "under 150 m²"),
        ("reason", "footprint>5000", "over 5000 m²"),
        ("reason", "outside residential land use", "outside residential zones"),
        ("residential", "excluded", "not a home"),
        ("floors", "unknown", "no number of floors"),
        ("reason", "other", "grouped"),
    ],
)
def test_legend_entries_are_explained(colour_by, value, expected):
    from map_routing.maps import explain

    assert expected in explain(colour_by, value)


def test_every_imputation_source_and_reason_has_an_explanation():
    """Values produced by the imputation rules must not show up unexplained."""
    from map_routing.maps import explain

    sources = [
        "osm",
        "height",
        "neighbours_300m",
        "area_median",
        "area_distribution",
        "default_median",
        "default_distribution",
        "none",
    ]
    reasons = [
        "footprint ok, residential land use",
        "outside residential land use",
        "footprint ok",
        "footprint<150",
        "footprint>5000",
        "building=yes",
        "amenity=school",
    ]
    assert all(explain("floors-source", v) for v in sources)
    assert all(explain("reason", v) for v in reasons)


def test_legends_have_subtitle_and_footer():
    page = buildings_map(buildings(6), AREA, colour_by="floors-source", sample=None)
    page = page.get_root().render()
    assert "where the building&#x27;s number of floors comes from" in page
    assert "Hover for a summary, click for details" in page
    page = scenario_map(scenario(), AREA).get_root().render()
    assert "Dot size: visits per week" in page and "picked at random from all" in page

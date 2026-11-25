"""API tests on a small data folder: one area with imputed buildings, one scenario."""

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box

from map_routing.api.app import create_app
from map_routing.api.areas import MAX_SAMPLE, MAX_SEED
from map_routing.area.model import AreaDefinition, make_area
from map_routing.geo import WGS84
from map_routing.scenario.io import write_scenario
from map_routing.settings import Settings
from map_routing.synthetic.generator import GeneratorConfig, generate

AREA = make_area(
    "testville",
    "Testville",
    AreaDefinition(kind="bbox", value="x"),
    box(22.90, 40.60, 22.97, 40.655),
)


def imputed_buildings(n: int = 1500) -> gpd.GeoDataFrame:
    rng = np.random.default_rng(0)
    lon, lat = rng.uniform(22.90, 22.97, n), rng.uniform(40.60, 40.655, n)
    reasons = np.array(
        ["footprint ok"] * 6
        + [
            "footprint<150",
            "building=apartments",
            "building=school",
            "amenity=school",
            "building=church",
            "building=garage",
            "building=roof",
        ]
    )
    reason = rng.choice(reasons, n)
    residential = np.isin(reason, ["footprint ok", "building=apartments"])
    floors = np.where(residential, rng.integers(1, 12, n).astype(float), np.nan)
    df = pd.DataFrame(
        {
            "osm_id": [f"w{i}" for i in range(n)],
            "building": "yes",
            "lon": lon,
            "lat": lat,
            "residential": residential,
            "residential_reason": reason,
            "floors": floors,
            "floors_source": np.where(residential, "osm", None),
            "footprint_m2": 200.0,
            "address": None,
            "address_source": None,
        }
    )
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(lon, lat), crs=WGS84)


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path, user_agent="test")
    area_dir = settings.area_dir("testville")
    AREA.save(area_dir)
    imputed_buildings().to_parquet(area_dir / "buildings.parquet")
    scenario = generate(area_dir, AREA, "small", 1, GeneratorConfig())
    write_scenario(scenario, settings.scenarios_dir / scenario.meta.name)
    # an area without imputed buildings
    make_area("empty", "Empty", AREA.definition, box(0, 0, 1, 1)).save(settings.area_dir("empty"))
    return TestClient(create_app(settings))


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_areas(client):
    areas = {a["slug"]: a for a in client.get("/api/areas").json()}
    assert set(areas) == {"testville", "empty"}
    assert areas["testville"]["has_buildings"] and not areas["empty"]["has_buildings"]
    assert areas["testville"]["bounds"] == {
        "west": 22.9,
        "south": 40.6,
        "east": 22.97,
        "north": 40.655,
    }
    detail = client.get("/api/areas/testville").json()
    assert detail["boundary"]["type"] == "Polygon"


def test_buildings_geojson_and_legend(client):
    r = client.get("/api/areas/testville/buildings", params={"sample": 300, "seed": 2})
    data = r.json()
    assert data["type"] == "FeatureCollection" and data["shown"] == 300 and data["sampled"]
    assert data["total"] == 1500
    f = data["features"][0]
    assert f["geometry"]["type"] == "Point" and len(f["geometry"]["coordinates"]) == 2
    legend = data["legend"]
    assert "300 of 1,500 buildings (random sample)" in legend["title"]
    assert sum(i["count"] for i in legend["items"]) == 300
    assert {i["value"] for i in legend["items"]} == {
        f["properties"]["category"] for f in data["features"]
    }
    assert all(i["description"] for i in legend["items"])
    counts = [i["count"] for i in legend["items"]]
    assert counts == sorted(counts, reverse=True)  # by frequency


def test_buildings_sample_is_reproducible(client):
    def ids(seed):
        r = client.get("/api/areas/testville/buildings", params={"sample": 50, "seed": seed})
        return [f["properties"]["osm_id"] for f in r.json()["features"]]

    assert ids(1) == ids(1) and ids(1) != ids(2)


def test_buildings_residential_only_all_and_floors(client):
    r = client.get(
        "/api/areas/testville/buildings",
        params={"residential_only": True, "all": True, "colour_by": "floors"},
    )
    data = r.json()
    assert not data["sampled"] and data["shown"] == data["total"]
    assert all(f["properties"]["residential"] for f in data["features"])
    values = [i["value"] for i in data["legend"]["items"]]
    bands = ["1–2 floors", "3–4 floors", "5–6 floors", "7–9 floors", "10+ floors"]
    assert values == [b for b in bands if b in values]  # natural order


def test_rare_categories_grouped_as_other(client):
    from map_routing.legends import MAX_CATEGORIES

    r = client.get("/api/areas/testville/buildings", params={"all": True, "colour_by": "reason"})
    items = r.json()["legend"]["items"]
    assert len(items) <= MAX_CATEGORIES + 1
    if any(i["value"] == "other" for i in items):
        assert items[-1]["value"] == "other"


def test_json_has_no_nan(client):
    r = client.get("/api/areas/testville/buildings", params={"all": True, "colour_by": "floors"})
    assert "NaN" not in r.text
    floors = [f["properties"]["floors"] for f in r.json()["features"]]
    assert None in floors  # non-residential buildings have no floors


@pytest.mark.parametrize(
    "params",
    [
        {"colour_by": "height"},
        {"sample": 0},
        {"sample": MAX_SAMPLE + 1},
        {"sample": 300, "seed": -1},
        {"sample": 300, "seed": MAX_SEED + 1},
    ],
)
def test_bad_parameters(client, params):
    assert client.get("/api/areas/testville/buildings", params=params).status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        "/api/areas/nope",
        "/api/areas/Bad_Slug",
        "/api/areas/..%2F..%2Fetc",
        "/api/areas/empty/buildings",
        "/api/scenarios/nope",
        "/api/scenarios/..%2Fareas",
    ],
)
def test_not_found(client, url):
    r = client.get(url)
    assert r.status_code == 404 and "detail" in r.json()


def test_scenarios(client):
    listing = client.get("/api/scenarios").json()
    assert [s["name"] for s in listing] == ["testville-small-s1"]
    assert listing[0]["locations"] == 100 and listing[0]["layout"] == "mixed"
    assert client.get("/api/scenarios", params={"area": "empty"}).json() == []

    data = client.get("/api/scenarios/testville-small-s1").json()
    assert data["type"] == "FeatureCollection" and len(data["features"]) == 100
    assert [d["group"] for d in data["dense_areas"]] == ["area1", "area2", "area3"]
    assert data["summary"]["size"] == "small" and data["summary"]["load"] == "moderate"
    groups = [i["value"] for i in data["legend"]["items"]]
    assert groups[:3] == ["area1", "area2", "area3"] and groups[-1] == "outlier"
    assert all(i["description"] for i in data["legend"]["items"])
    props = data["features"][0]["properties"]
    assert props["group"].startswith("area") or props["group"] == "outlier"
    assert isinstance(props["allowed_days"], list)


def test_largest_seed_is_accepted(client):
    params = {"sample": 300, "seed": MAX_SEED}
    assert client.get("/api/areas/testville/buildings", params=params).status_code == 200


def broken_data_client(tmp_path):
    """The `client` data plus a broken area and a broken scenario next to them."""
    settings = Settings(data_dir=tmp_path, user_agent="test")
    area_dir = settings.area_dir("testville")
    AREA.save(area_dir)
    imputed_buildings().to_parquet(area_dir / "buildings.parquet")
    scenario = generate(area_dir, AREA, "small", 1, GeneratorConfig())
    write_scenario(scenario, settings.scenarios_dir / scenario.meta.name)
    broken_area = settings.area_dir("broken")
    broken_area.mkdir(parents=True)
    (broken_area / "area.json").write_text("{not json")
    broken_scenario = settings.scenarios_dir / "testville-broken"
    broken_scenario.mkdir(parents=True)
    (broken_scenario / "scenario.json").write_text('{"name": "testville-broken"}')
    return TestClient(create_app(settings), raise_server_exceptions=False)


def test_broken_files_are_skipped_in_listings(tmp_path):
    client = broken_data_client(tmp_path)
    areas = client.get("/api/areas")
    assert areas.status_code == 200 and [a["slug"] for a in areas.json()] == ["testville"]
    scenarios = client.get("/api/scenarios")
    assert scenarios.status_code == 200
    assert [s["name"] for s in scenarios.json()] == ["testville-small-s1"]


@pytest.mark.parametrize(
    "url, hint",
    [
        ("/api/areas/broken", "area define"),
        ("/api/scenarios/testville-broken", "scenario generate"),
    ],
)
def test_broken_file_gives_a_clear_error(tmp_path, url, hint):
    r = broken_data_client(tmp_path).get(url)
    assert r.status_code == 500 and hint in r.json()["detail"]


def test_buildings_of_one_area_load_without_blocking_another(tmp_path, monkeypatch):
    """Loading a large area (slow parquet read) must not hold up a cached area."""
    import threading

    from map_routing.api import data

    settings = Settings(data_dir=tmp_path, user_agent="test")
    for slug in ("fast", "slow"):
        make_area(slug, slug, AREA.definition, AREA.geometry).save(settings.area_dir(slug))
        imputed_buildings(10).to_parquet(settings.area_dir(slug) / "buildings.parquet")
    store = data.DataStore(settings)
    store.buildings("fast")  # cached

    loading, release = threading.Event(), threading.Event()
    read_parquet = data.gpd.read_parquet

    def slow_read(path, *args, **kwargs):
        loading.set()
        release.wait(timeout=10)
        return read_parquet(path, *args, **kwargs)

    monkeypatch.setattr(data.gpd, "read_parquet", slow_read)
    slow = threading.Thread(target=store.buildings, args=("slow",))
    slow.start()
    assert loading.wait(timeout=5)
    try:
        fast = threading.Thread(target=store.buildings, args=("fast",))
        fast.start()
        fast.join(timeout=2)
        assert not fast.is_alive(), "the cached area waited for another area's load"
    finally:
        release.set()
        slow.join()


def test_nullable_columns_are_served_as_null(tmp_path):
    """Missing values stored as pd.NA (nullable dtypes) become JSON null, not "<NA>"."""
    settings = Settings(data_dir=tmp_path, user_agent="test")
    area_dir = settings.area_dir("testville")
    AREA.save(area_dir)
    b = imputed_buildings(50)
    b["floors"] = b["floors"].astype("Float64")
    b["address"] = b["address"].astype("string")
    b.to_parquet(area_dir / "buildings.parquet")
    r = TestClient(create_app(settings)).get("/api/areas/testville/buildings", params={"all": True})
    assert r.status_code == 200
    props = [f["properties"] for f in r.json()["features"]]
    assert all(p["address"] is None for p in props)
    assert None in [p["floors"] for p in props]


def test_buildings_cache_reloads_when_file_changes(tmp_path):
    import os

    settings = Settings(data_dir=tmp_path, user_agent="test")
    area_dir = settings.area_dir("testville")
    AREA.save(area_dir)
    path = area_dir / "buildings.parquet"
    imputed_buildings(100).to_parquet(path)
    client = TestClient(create_app(settings))
    url = "/api/areas/testville/buildings"
    assert client.get(url, params={"all": True}).json()["total"] == 100
    imputed_buildings(40).to_parquet(path)
    os.utime(path, (1e9, 1e9))  # make sure the modification time differs
    assert client.get(url, params={"all": True}).json()["total"] == 40


def test_openapi_describes_the_models(client):
    schema = client.get("/openapi.json").json()
    for name in ("BuildingCollection", "ScenarioDetail", "DenseAreaDetail", "Legend", "AreaDetail"):
        assert name in schema["components"]["schemas"]


def test_endpoints(client):
    """The URLs the web app uses; the store is injected, never a request parameter."""
    schema = client.get("/openapi.json").json()
    assert sorted(schema["paths"]) == [
        "/api/areas",
        "/api/areas/{slug}",
        "/api/areas/{slug}/buildings",
        "/api/health",
        "/api/scenarios",
        "/api/scenarios/{name}",
    ]
    parameters = [
        p["name"]
        for path in schema["paths"].values()
        for operation in path.values()
        for p in operation.get("parameters", [])
    ]
    assert "store" not in parameters


def test_apps_with_different_settings_do_not_share_data(client, tmp_path):
    other = TestClient(create_app(Settings(data_dir=tmp_path / "other", user_agent="test")))
    assert other.get("/api/areas").json() == []
    assert [a["slug"] for a in client.get("/api/areas").json()] == ["empty", "testville"]


def test_api_models_never_reuse_core_names():
    """Naming rule: API models are a separate layer and must not shadow core models."""
    import inspect

    from pydantic import BaseModel

    import map_routing.api.models as api
    import map_routing.area.model as area
    import map_routing.buildings.rules as rules
    import map_routing.scenario.schema as schema
    import map_routing.synthetic.generator as generator

    def models(module):
        return {
            name
            for name, obj in vars(module).items()
            if inspect.isclass(obj)
            and issubclass(obj, BaseModel)
            and obj.__module__ == module.__name__
        }

    core = set().union(*(models(m) for m in (area, rules, schema, generator)))
    assert {"Area", "Scenario", "Location", "DenseArea"} <= core
    assert models(api) and not (models(api) & core)

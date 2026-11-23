import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from map_routing.area.model import AreaDefinition, make_area
from map_routing.geo import WGS84
from map_routing.scenario.io import read_scenario, write_scenario
from map_routing.scenario.schema import outside
from map_routing.synthetic.generator import SIZES, GeneratorConfig, generate

AREA = make_area("syn", "Syn", AreaDefinition(kind="bbox", value="x"), box(22.8, 40.5, 23.1, 40.8))


@pytest.fixture
def area_dir(tmp_path):
    """A pool of 4,000 buildings (90 % residential) in a ~6 x 6 km city."""
    rng = np.random.default_rng(0)
    n = 4000
    lon = rng.uniform(22.90, 22.97, n)
    lat = rng.uniform(40.60, 40.655, n)
    df = pd.DataFrame(
        {
            "osm_id": [f"w{i}" for i in range(n)],
            "lon": lon,
            "lat": lat,
            "residential": True,
            "floors": rng.integers(1, 9, n).astype(float),
            "floors_source": "osm",
            "footprint_m2": 200.0,
            "address": [None] * n,
            "address_source": [None] * n,
        }
    )
    df.loc[::10, "residential"] = False
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(lon, lat), crs=WGS84)
    gdf.to_parquet(tmp_path / "buildings.parquet")
    return tmp_path


def test_deterministic_and_nested(area_dir):
    cfg = GeneratorConfig()
    small = generate(area_dir, AREA, "small", 3, cfg)
    full = generate(area_dir, AREA, "full", 3, cfg)
    again = generate(area_dir, AREA, "full", 3, cfg)
    assert [loc.model_dump() for loc in full.locations] == [
        loc.model_dump() for loc in again.locations
    ]
    assert small.locations == full.locations[: SIZES["small"]]
    other = generate(area_dir, AREA, "full", 4, cfg)
    assert {loc.osm_id for loc in other.locations} != {loc.osm_id for loc in full.locations}


def test_mixture_proportions_and_validity(area_dir, tmp_path_factory):
    inst = generate(area_dir, AREA, "full", 1, GeneratorConfig())
    counts = inst.meta.synthetic.component_counts
    assert sum(counts.values()) == 1000
    assert abs(counts["area1"] / 1000 - 0.50) < 0.06
    assert abs(counts["outlier"] / 1000 - 0.05) < 0.03
    assert len({loc.osm_id for loc in inst.locations}) == 1000  # no building twice
    assert all(
        loc.osm_id and int(loc.osm_id[1:]) % 10 != 0 for loc in inst.locations
    )  # residential only
    assert outside(inst, AREA.geometry) == []
    out = tmp_path_factory.mktemp("inst")
    write_scenario(inst, out)
    assert read_scenario(out).visits_per_week == inst.visits_per_week


def test_dense_areas_are_dense(area_dir):
    from map_routing.synthetic.generator import load_pool, sample_order

    pool = load_pool(area_dir)
    order, labels, info = sample_order(
        pool, AREA, GeneratorConfig(), np.random.default_rng(1), 1000
    )
    labels = np.array(labels)
    lon, lat = pool.lon.to_numpy()[order], pool.lat.to_numpy()[order]

    def dist_m(c, mask):
        return np.hypot((lon[mask] - c.lon) * 84_400, (lat[mask] - c.lat) * 111_000)

    dense_areas, _ = info
    centre = dense_areas[0]
    assert centre.component == "area1"
    area1 = np.median(dist_m(centre, labels == "area1"))
    assert area1 < 2.5 * centre.sigma_m
    assert np.median(dist_m(centre, labels == "outlier")) > 1.5 * area1


def test_load_levels(area_dir):
    moderate = generate(area_dir, AREA, "full", 1, GeneratorConfig(load="moderate"))
    high = generate(area_dir, AREA, "full", 1, GeneratorConfig(load="high"))
    assert 1800 < moderate.visits_per_week < 2300
    assert 4300 < high.visits_per_week < 4800
    assert all(loc.visits_per_week <= 5 for loc in high.locations)


def test_demand_ranges_and_forbidden_days(area_dir):
    inst = generate(area_dir, AREA, "full", 1, GeneratorConfig())
    assert all(15 <= loc.duration_min <= 90 for loc in inst.locations)
    restricted = [loc for loc in inst.locations if len(loc.allowed_days) == 4]
    assert 50 < len(restricted) < 150  # ~10 %
    assert all(
        set(loc.allowed_days) <= {"Mon", "Tue", "Wed", "Thu", "Fri"} for loc in inst.locations
    )


def test_compact_layout(area_dir):
    inst = generate(area_dir, AREA, "small", 1, GeneratorConfig(layout="compact"))
    assert inst.meta.synthetic.component_counts == {"area1": 100}
    assert inst.meta.name == "syn-small-compact-s1"


def test_small_area_still_gives_nested_small_and_medium(tmp_path, area_dir):
    """An area with fewer residential buildings than `full` can still give smaller sizes."""
    b = gpd.read_parquet(area_dir / "buildings.parquet").head(500)  # 450 residential
    b.to_parquet(tmp_path / "buildings.parquet")
    small = generate(tmp_path, AREA, "small", 1, GeneratorConfig())
    medium = generate(tmp_path, AREA, "medium", 1, GeneratorConfig())
    assert len(small.locations) == 100
    assert small.locations == medium.locations[:100]
    with pytest.raises(ValueError, match="need 1000"):
        generate(tmp_path, AREA, "full", 1, GeneratorConfig())


def test_zero_footprint_does_not_crash(tmp_path, area_dir):
    b = gpd.read_parquet(area_dir / "buildings.parquet")
    b["footprint_m2"] = 0.0  # degenerate outlines, e.g. a mis-drawn building=house
    b.to_parquet(tmp_path / "buildings.parquet")
    inst = generate(tmp_path, AREA, "small", 1, GeneratorConfig())
    assert all(loc.footprint_m2 is None for loc in inst.locations)


@pytest.mark.parametrize(
    "kw",
    [
        {"n_centres": 2},
        {"component_weights": [0.6, 0.3, 0.2]},
        {"component_weights": [0.5, -0.1, 0.1]},
    ],
)
def test_inconsistent_component_settings_are_rejected(kw):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GeneratorConfig(**kw)


def test_two_centres_when_configured_consistently(area_dir):
    cfg = GeneratorConfig(n_centres=2, component_weights=[0.6, 0.3], component_sigma_m=[700, 500])
    inst = generate(area_dir, AREA, "small", 1, cfg)
    assert set(inst.meta.synthetic.component_counts) <= {"area1", "area2", "outlier"}


@pytest.mark.parametrize("option,value", [("--layout", "spiral"), ("--load", "heavy")])
def test_cli_rejects_unknown_choices_cleanly(option, value):
    from typer.testing import CliRunner

    from map_routing.cli import app

    result = CliRunner().invoke(app, ["scenario", "generate", "x", option, value])
    assert result.exit_code == 2  # usage error, no traceback
    assert option in result.output and "must be one of" in result.output

import json

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, box

from map_routing.area.model import AreaDefinition, make_area
from map_routing.buildings.impute import impute
from map_routing.buildings.rules import ImputationConfig, parse_number
from map_routing.geo import WGS84

LON0, LAT0 = 22.95, 40.62
M_LON = 1 / 84_400  # degrees of longitude per metre at 40.6°N (approx.)
M_LAT = 1 / 111_000

AREA = make_area("t", "T", AreaDefinition(kind="bbox", value="x"), box(22.9, 40.6, 23.0, 40.7))


def building(x_m, y_m, building="yes", footprint=200.0, **tags):
    lon, lat = LON0 + x_m * M_LON, LAT0 + y_m * M_LAT
    row = {
        "osm_id": f"w{abs(hash((x_m, y_m))) % 10**8}",
        "building": building,
        "building_levels": None,
        "height": None,
        "addr_street": None,
        "addr_housenumber": None,
        "amenity": None,
        "shop": None,
        "landuse": None,
        "tags": json.dumps(tags),
        "footprint_m2": footprint,
        "lon": lon,
        "lat": lat,
    }
    row.update(tags)
    return row, Point(lon, lat)


def gdf(items):
    rows, geoms = zip(*items, strict=True)
    return gpd.GeoDataFrame(pd.DataFrame(list(rows)), geometry=list(geoms), crs=WGS84)


def context(landuse_boxes_m=(), addresses=()):
    rows, geoms = [], []
    for x0, y0, x1, y1 in landuse_boxes_m:
        rows.append({"kind": "residential_landuse", "addr_street": None, "addr_housenumber": None})
        geoms.append(
            box(LON0 + x0 * M_LON, LAT0 + y0 * M_LAT, LON0 + x1 * M_LON, LAT0 + y1 * M_LAT)
        )
    for x, y, street, number in addresses:
        rows.append({"kind": "address", "addr_street": street, "addr_housenumber": number})
        geoms.append(Point(LON0 + x * M_LON, LAT0 + y * M_LAT))
    cols = ["kind", "addr_street", "addr_housenumber"]
    return gpd.GeoDataFrame(pd.DataFrame(rows, columns=cols), geometry=geoms, crs=WGS84)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("6", 6.0),
        ("4;5", 4.0),
        ("18 m", 18.0),
        ("2,5", 2.5),
        (None, None),
        ("many", None),
        (float("nan"), None),
    ],
)
def test_parse_number(value, expected):
    assert parse_number(value) == expected


def test_residential_rules_with_landuse():
    b = gdf(
        [
            building(0, 0, "apartments"),
            building(50, 0, "school"),
            building(100, 0, "yes", amenity="place_of_worship"),
            building(150, 0, "yes", footprint=30),
            building(200, 0, "yes", footprint=9000),
            building(250, 0, "yes"),  # inside land use
            building(2000, 0, "yes"),  # outside land use
            building(300, 0, "yes", shop="bakery"),  # shop on ground floor stays residential
        ]
    )
    ctx = context(landuse_boxes_m=[(-20, -20, 400, 20)])
    out, q = impute(b, ctx, AREA, ImputationConfig(landuse_min_coverage=0.5))
    reasons = dict(zip(out.index, out.residential_reason, strict=True))
    assert out.residential.tolist() == [True, False, False, False, False, True, False, True]
    assert reasons[0] == "building=apartments" and reasons[2] == "amenity=place_of_worship"
    assert reasons[3] == "footprint<50" and reasons[4] == "footprint>5000"
    assert reasons[6] == "outside residential land use"
    assert out.residential_source.tolist()[:3] == ["osm", "osm", "osm"]
    assert q["notes"]["landuse_used"] is True


def test_small_untyped_house_counts_as_residential():
    """A family house often covers 80-110 m² of ground; only sheds, garages and kiosks
    (typically 20-30 m²) are too small to be homes."""
    b = gdf([building(0, 0, "yes", footprint=80), building(50, 0, "yes", footprint=25)])
    out, _ = impute(b, context(), AREA, ImputationConfig(landuse_mode="ignore"))
    assert out.residential.tolist() == [True, False]
    assert out.residential_reason.tolist()[1] == "footprint<50"


def test_landuse_ignored_when_poorly_mapped():
    b = gdf([building(i * 50, 0) for i in range(10)])
    ctx = context(landuse_boxes_m=[(-20, -20, 20, 20)])  # covers 1 of 10 buildings
    out, q = impute(b, ctx, AREA, ImputationConfig())
    assert q["notes"]["landuse_used"] is False
    assert out.residential.all() and set(out.residential_reason) == {"footprint ok"}


def test_floors_chain():
    observed = [building(i * 20, 0, "apartments", building_levels=str(6)) for i in range(5)]
    items = observed + [
        building(0, 40, "apartments"),  # 5 observed within 300 m -> median 6
        building(0, 0, "apartments", height="15 m"),  # height 15 / 3 = 5
        building(0, 700, "apartments"),  # only within 1000 m
        building(10_000, 0, "apartments"),  # far away, too few observed -> default
    ]
    cfg = ImputationConfig(landuse_mode="ignore", min_observed_for_area_distribution=100)
    out, _ = impute(gdf(items), context(), AREA, cfg)
    tail = out.iloc[5:]
    assert tail.floors_source.tolist() == [
        "neighbours_300m",
        "height",
        "neighbours_1000m",
        "default_median",
    ]
    assert tail.floors.tolist() == [6.0, 5.0, 6.0, 2.0]  # default median of 1-4 (.2/.3/.3/.2)
    assert out.iloc[:5].floors_source.eq("osm").all()


def test_area_distribution_fallback_is_seeded():
    observed = [
        building(i * 30, 0, "apartments", building_levels=str(3 + i % 4)) for i in range(40)
    ]
    far = [building(20_000 + i * 10, 0, "apartments") for i in range(5)]
    cfg = ImputationConfig(
        landuse_mode="ignore",
        min_observed_for_area_distribution=30,
        seed=7,
        floor_fallback="random",
    )
    a, _ = impute(gdf(observed + far), context(), AREA, cfg)
    b, _ = impute(gdf(observed + far), context(), AREA, cfg)
    assert a.iloc[40:].floors_source.eq("area_distribution").all()
    assert set(a.iloc[40:].floors) <= {3.0, 4.0, 5.0, 6.0}
    assert np.array_equal(a.floors.to_numpy(), b.floors.to_numpy())


def test_non_residential_get_no_imputed_floors():
    out, _ = impute(
        gdf([building(0, 0, "school")]), context(), AREA, ImputationConfig(landuse_mode="ignore")
    )
    assert np.isnan(out.floors.iloc[0]) and out.floors_source.iloc[0] is None


def test_address_own_then_nearest():
    b = gdf(
        [
            building(0, 0, "apartments", addr_street="Egnatia", addr_housenumber="1"),
            building(100, 0, "apartments"),  # address point 10 m away
            building(500, 0, "apartments"),  # nothing within 30 m
        ]
    )
    ctx = context(addresses=[(110, 0, "Tsimiski", "5")])
    out, _ = impute(b, ctx, AREA, ImputationConfig(landuse_mode="ignore"))
    assert out.address.tolist() == ["Egnatia 1", "Tsimiski 5", None]
    assert out.address_source.tolist() == ["osm", "nearest_point", None]


def test_area_median_fallback_is_default():
    """Real data gets one fixed, explainable value, not a random draw."""
    floors = [3 + i % 4 for i in range(40)]
    observed = [
        building(i * 30, 0, "apartments", building_levels=str(f)) for i, f in enumerate(floors)
    ]
    far = [building(20_000 + i * 10, 0, "apartments") for i in range(5)]
    cfg = ImputationConfig(landuse_mode="ignore", min_observed_for_area_distribution=30)
    out, _ = impute(gdf(observed + far), context(), AREA, cfg)
    assert out.iloc[40:].floors_source.eq("area_median").all()
    assert out.iloc[40:].floors.eq(np.round(np.median(floors))).all()


@pytest.mark.parametrize(
    "values,weights,expected",
    [
        ([1, 2, 3, 4], [0.2, 0.3, 0.3, 0.2], 2.0),
        ([5, 1, 3], [1, 1, 1], 3.0),
        ([1, 9], [0.1, 0.9], 9.0),
    ],
)
def test_weighted_median(values, weights, expected):
    from map_routing.buildings.rules import weighted_median

    assert weighted_median(np.array(values, float), np.array(weights, float)) == expected


def test_neighbour_median_needs_k_observed_buildings():
    """One tagged 12-floor building must not set the floors of everything nearby."""
    items = [building(0, 0, "apartments", building_levels="12")] + [
        building(20 * i, 50, "apartments") for i in range(1, 6)
    ]
    cfg = ImputationConfig(landuse_mode="ignore")
    out, _ = impute(gdf(items), context(), AREA, cfg)
    assert out.iloc[1:].floors_source.eq("default_median").all()
    assert out.iloc[1:].floors.eq(2.0).all()


def test_explicit_config_must_exist(tmp_path):
    from map_routing.buildings.impute import load_config

    assert load_config(tmp_path) == ImputationConfig()  # implicit file is optional
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path, tmp_path / "imputaton.json")
    (tmp_path / "custom.json").write_text('{"min_footprint_m2": 80}')
    assert load_config(tmp_path, tmp_path / "custom.json").min_footprint_m2 == 80

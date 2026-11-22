import json
from pathlib import Path

import geopandas as gpd
import pytest

from map_routing import osmium
from map_routing.area.model import AreaDefinition, make_area, parse_bbox
from map_routing.buildings.extract import extract_buildings

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.osm"

pytestmark = pytest.mark.osmium


@pytest.fixture
def area_dir(tmp_path):
    if not osmium.available():
        pytest.skip("osmium not installed")
    osmium.run("cat", "--overwrite", "-o", tmp_path / "area.osm.pbf", FIXTURE)
    return tmp_path


def test_extract_fixture(area_dir):
    bbox = "22.94,40.61,22.96,40.63"
    area = make_area("tiny", "Tiny", AreaDefinition(kind="bbox", value=bbox), parse_bbox(bbox))
    buildings_path, context_path = extract_buildings(area, area_dir)

    b = gpd.read_parquet(buildings_path)
    assert len(b) == 9  # 8 closed ways + 1 multipolygon relation, each exactly once
    assert set(b.osm_id) == {f"w{200 + i}" for i in range(8)} | {"r500"}
    first = b.set_index("osm_id").loc["w200"]
    assert first.building == "apartments" and first.building_levels == "6"
    assert json.loads(first.tags)["addr:street"] == "Egnatia"
    assert 300 < first.footprint_m2 < 450  # ~17 m x ~22 m
    rel = b.set_index("osm_id").loc["r500"]
    assert rel.geometry.geom_type == "MultiPolygon"  # courtyard kept as a hole

    c = gpd.read_parquet(context_path)
    assert c.kind.value_counts().to_dict() == {"address": 2, "residential_landuse": 1}
    assert not list(area_dir.glob("*.geojsonseq"))  # temporary files removed

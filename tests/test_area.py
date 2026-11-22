import json

import pytest
from pydantic import ValidationError
from shapely.geometry import Point, box, mapping

from map_routing.area.model import (
    Area,
    AreaDefinition,
    make_area,
    parse_bbox,
    read_polygon_file,
)


def test_parse_bbox():
    assert parse_bbox("22.85,40.55,23.05,40.70").bounds == (22.85, 40.55, 23.05, 40.70)


@pytest.mark.parametrize("text", ["1,2,3", "a,b,c,d", "23,40,22,41", "0,50,1,40"])
def test_parse_bbox_rejects(text):
    with pytest.raises(ValueError):
        parse_bbox(text)


def test_round_trip(tmp_path):
    area = make_area(
        "thess-test", "T", AreaDefinition(kind="bbox", value="0,0,1,1"), box(0, 0, 1, 1)
    )
    area.save(tmp_path)
    loaded = Area.load(tmp_path)
    assert loaded == area
    assert loaded.geometry.equals(box(0, 0, 1, 1))


def test_rejects_bad_slug_and_point():
    d = AreaDefinition(kind="bbox", value="x")
    with pytest.raises(ValidationError):
        make_area("Bad Slug", "x", d, box(0, 0, 1, 1))
    with pytest.raises(ValidationError):
        make_area("ok", "x", d, Point(0, 0))


def test_read_polygon_file_feature_collection(tmp_path):
    p = tmp_path / "b.geojson"
    p.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {}, "geometry": mapping(box(1, 1, 2, 2))}
                ],
            }
        )
    )
    assert read_polygon_file(p).equals(box(1, 1, 2, 2))


def test_load_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        Area.load(tmp_path)

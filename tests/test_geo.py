import pytest
from shapely.geometry import box

from map_routing.geo import utm_crs, utm_crs_for


def test_thessaloniki_is_zone_34_north():
    assert utm_crs(22.94, 40.64).to_epsg() == 32634


def test_southern_hemisphere():
    assert utm_crs(151.2, -33.9).to_epsg() == 32756  # Sydney


def test_edges():
    assert utm_crs(-180.0, 0.0).to_epsg() == 32601
    assert utm_crs(180.0, 0.0).to_epsg() == 32660


def test_from_geometry_centroid():
    assert utm_crs_for(box(17.0, 48.1, 17.2, 48.2)).to_epsg() == 32633  # Bratislava


def test_invalid():
    with pytest.raises(ValueError):
        utm_crs(200.0, 0.0)


def test_reproject_area_of_one_degree_cell_at_equator():
    from map_routing.geo import EQUAL_AREA, WGS84, reproject

    km2 = reproject(box(0, 0, 1, 1), WGS84, EQUAL_AREA).area / 1e6
    assert 12_300 < km2 < 12_400  # ~111.3 km x 110.6 km

import json

import pytest
from shapely.geometry import box, mapping

from map_routing.providers.geocoding import GeocodingError, NominatimGeocoder

RESULT = [
    {
        "osm_type": "relation",
        "osm_id": 42,
        "display_name": "Testville",
        "geojson": mapping(box(1, 1, 2, 2)),
    }
]


class FakeClock:
    def __init__(self):
        self.t = 100.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def test_geocode_and_cache(tmp_path):
    urls = []

    def fetch(url, ua):
        urls.append((url, ua))
        return json.dumps(RESULT).encode()

    g = NominatimGeocoder(tmp_path, "test-agent/1", fetch=fetch)
    place = g.geocode("Testville")
    assert place.geometry.equals(box(1, 1, 2, 2))
    assert place.source == "nominatim:relation/42"
    assert "polygon_geojson=1" in urls[0][0] and urls[0][1] == "test-agent/1"
    g.geocode("  testville ")  # same query after normalisation: from cache
    assert len(urls) == 1


def test_rate_limit(tmp_path):
    clock = FakeClock()
    g = NominatimGeocoder(
        tmp_path,
        "ua",
        fetch=lambda u, a: json.dumps(RESULT).encode(),
        clock=clock.now,
        sleep=clock.sleep,
    )
    g.geocode("a")
    clock.t += 0.3
    g.geocode("b")
    assert clock.slept == [pytest.approx(0.7)]


def test_nothing_found(tmp_path):
    g = NominatimGeocoder(tmp_path, "ua", fetch=lambda u, a: b"[]")
    with pytest.raises(GeocodingError):
        g.geocode("nowhere")

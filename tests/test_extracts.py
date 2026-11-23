import json
import os

import pytest
from shapely.geometry import box, mapping

from map_routing.area.extracts import (
    INDEX_URL,
    Extract,
    GeofabrikIndex,
    ensure_downloaded,
    local_path,
)

BASE = "https://download.geofabrik.de"


def feature(id_, geom, url=True):
    props = {"id": id_, "name": id_.title()}
    if url:
        props["urls"] = {"pbf": f"{BASE}/{id_}-latest.osm.pbf"}
    return {"type": "Feature", "properties": props, "geometry": mapping(geom)}


FAKE_INDEX = {
    "type": "FeatureCollection",
    "features": [
        feature("europe", box(-10, 35, 30, 70)),
        feature("europe/greece", box(19, 34, 30, 42)),
        feature("europe/slovakia", box(16, 47, 23, 50)),
        feature("no-pbf", box(22, 40, 24, 41), url=False),
    ],
}


def test_smallest_containing_picks_country():
    index = GeofabrikIndex.from_geojson(FAKE_INDEX)
    assert index.smallest_containing(box(22.85, 40.55, 23.05, 40.70)).id == "europe/greece"


def test_area_across_borders_falls_back_to_continent():
    index = GeofabrikIndex.from_geojson(FAKE_INDEX)
    assert index.smallest_containing(box(22, 41, 24, 48)).id == "europe"


def test_nothing_contains():
    with pytest.raises(LookupError):
        GeofabrikIndex.from_geojson(FAKE_INDEX).smallest_containing(box(100, 0, 101, 1))


def test_index_cache(tmp_path):
    calls = []

    def fetch(url, ua):
        calls.append(url)
        return json.dumps(FAKE_INDEX).encode()

    GeofabrikIndex.load(tmp_path, "ua", fetch=fetch, now=lambda: 0)
    path = tmp_path / "index-v1.json"
    os.utime(path, (1000, 1000))
    GeofabrikIndex.load(tmp_path, "ua", fetch=fetch, now=lambda: 1000 + 3600)  # fresh
    assert calls == [INDEX_URL]
    GeofabrikIndex.load(tmp_path, "ua", fetch=fetch, now=lambda: 1000 + 8 * 24 * 3600)  # stale
    assert calls == [INDEX_URL, INDEX_URL]


def _extract():
    return Extract(
        "europe/greece", "Greece", f"{BASE}/europe/greece-latest.osm.pbf", box(0, 0, 1, 1)
    )


def test_local_path_mirrors_url(tmp_path):
    assert local_path(tmp_path, _extract()) == tmp_path / "europe/greece-latest.osm.pbf"


def test_download_checks_md5(tmp_path):
    content = b"pbf bytes"
    good = "8f3d6e6d2b5f4d4c2e2b4a6e7b6f0c1a"  # wrong on purpose first

    def download(url, target, ua):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    with pytest.raises(OSError, match="md5 mismatch"):
        ensure_downloaded(
            tmp_path, _extract(), "ua", fetch=lambda u, a: good.encode(), download=download
        )
    assert not local_path(tmp_path, _extract()).exists()

    import hashlib

    real = hashlib.md5(content).hexdigest()
    path = ensure_downloaded(
        tmp_path, _extract(), "ua", fetch=lambda u, a: f"{real}  x.pbf".encode(), download=download
    )
    assert path.read_bytes() == content


def test_existing_file_is_reused(tmp_path):
    path = local_path(tmp_path, _extract())
    path.parent.mkdir(parents=True)
    path.write_bytes(b"old")

    def fail(*a):
        raise AssertionError("must not download")

    assert ensure_downloaded(tmp_path, _extract(), "ua", fetch=fail, download=fail) == path


def test_broken_index_download_is_not_cached(tmp_path):
    def truncated(url, ua):
        return b'{"type": "FeatureCollection", "feat'

    with pytest.raises(ValueError):
        GeofabrikIndex.load(tmp_path, "ua", fetch=truncated, now=lambda: 0)
    assert not (tmp_path / "index-v1.json").exists()
    assert not list(tmp_path.glob("*.part"))


def test_failed_refresh_falls_back_to_stale_cache(tmp_path):
    path = tmp_path / "index-v1.json"
    path.write_text(json.dumps(FAKE_INDEX))
    os.utime(path, (0, 0))

    def offline(url, ua):
        raise OSError("network down")

    with pytest.warns(UserWarning, match="using the cached copy"):
        index = GeofabrikIndex.load(tmp_path, "ua", fetch=offline, now=lambda: 30 * 24 * 3600)
    assert len(index.extracts) == 3

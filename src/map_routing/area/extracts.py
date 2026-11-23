"""Geofabrik extracts: choose the smallest one covering an area, download, cut."""

import hashlib
import json
import time
import urllib.parse
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from map_routing import osmium
from map_routing.area.model import Area, SourceExtract
from map_routing.geo import EQUAL_AREA, WGS84, reproject
from map_routing.providers import http

INDEX_URL = "https://download.geofabrik.de/index-v1.json"
INDEX_MAX_AGE_S = 7 * 24 * 3600


@dataclass(frozen=True)
class Extract:
    id: str
    name: str
    pbf_url: str
    geometry: BaseGeometry

    @property
    def size_km2(self) -> float:
        return reproject(self.geometry, WGS84, EQUAL_AREA).area / 1e6


class GeofabrikIndex:
    def __init__(self, extracts: list[Extract]) -> None:
        self.extracts = extracts

    @classmethod
    def from_geojson(cls, data: dict) -> GeofabrikIndex:
        extracts = []
        for feature in data["features"]:
            props = feature.get("properties", {})
            url = props.get("urls", {}).get("pbf")
            if not url or not feature.get("geometry"):
                continue
            geom = shape(feature["geometry"])
            extracts.append(Extract(props["id"], props.get("name", props["id"]), url, geom))
        return cls(extracts)

    @classmethod
    def load(
        cls,
        cache_dir: Path,
        user_agent: str,
        fetch: Callable[[str, str], bytes] = http.get,
        now: Callable[[], float] = time.time,
    ) -> GeofabrikIndex:
        """Index from the cache; refreshed when older than a week."""
        path = cache_dir / "index-v1.json"
        if not path.exists() or now() - path.stat().st_mtime > INDEX_MAX_AGE_S:
            try:
                data = fetch(INDEX_URL, user_agent)
                json.loads(data)  # never cache a truncated or broken index
            except (OSError, ValueError) as exc:
                if not path.exists():
                    raise
                warnings.warn(
                    f"Geofabrik index refresh failed ({exc}); using the cached copy", stacklevel=2
                )
            else:
                # Write to a temporary file, then rename it over the cache. Writing the
                # cache directly would first truncate it: if the process were killed or
                # the disk filled up halfway, a half-written file with a fresh timestamp
                # would remain, count as valid for a week and break every `area fetch`.
                # A rename within one filesystem is atomic, so readers always see either
                # the old or the new complete file. (Not protected against power loss,
                # which would need fsync; acceptable for a cache that can be downloaded
                # again.)
                path.parent.mkdir(parents=True, exist_ok=True)
                partial = path.with_name(path.name + ".part")
                partial.write_bytes(data)
                partial.replace(path)
        return cls.from_geojson(json.loads(path.read_text()))

    def smallest_containing(self, area: BaseGeometry) -> Extract:
        candidates = [e for e in self.extracts if e.geometry.contains(area)]
        if not candidates:
            raise LookupError("no Geofabrik extract contains the whole area")
        return min(candidates, key=lambda e: e.size_km2)


def local_path(cache_dir: Path, extract: Extract) -> Path:
    """Mirror Geofabrik's URL path, e.g. europe/greece/greece-latest.osm.pbf."""
    return cache_dir / urllib.parse.urlparse(extract.pbf_url).path.lstrip("/")


def md5sum(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def ensure_downloaded(
    cache_dir: Path,
    extract: Extract,
    user_agent: str,
    refresh: bool = False,
    fetch: Callable[[str, str], bytes] = http.get,
    download: Callable[[str, Path, str], None] = http.download,
) -> Path:
    """Download an extract once; check it against Geofabrik's .md5 published with it.
    An existing file is reused (fixed data date) unless `refresh` is set."""
    path = local_path(cache_dir, extract)
    if path.exists() and not refresh:
        return path
    expected = fetch(extract.pbf_url + ".md5", user_agent).decode().split()[0]
    download(extract.pbf_url, path, user_agent)
    actual = md5sum(path)
    if actual != expected:
        path.unlink()
        raise OSError(f"md5 mismatch for {extract.pbf_url}: {actual} != {expected}")
    return path


def fetch_area(
    area: Area,
    area_dir: Path,
    cache_dir: Path,
    user_agent: str,
    refresh: bool = False,
) -> Path:
    """Choose, download and cut the extract for an area; record the source and
    data date in the area. Returns the path of area.osm.pbf."""
    index = GeofabrikIndex.load(cache_dir, user_agent)
    extract = index.smallest_containing(area.geometry)
    source = ensure_downloaded(cache_dir, extract, user_agent, refresh=refresh)

    boundary_file = area_dir / "boundary.geojson"
    boundary_file.write_text(
        json.dumps({"type": "Feature", "properties": {}, "geometry": mapping(area.geometry)})
    )
    target = area_dir / "area.osm.pbf"
    osmium.extract(source, boundary_file, target)

    area.source_extract = SourceExtract(id=extract.id, name=extract.name, url=extract.pbf_url)
    area.data_date = osmium.data_timestamp(source)
    area.save(area_dir)
    return target

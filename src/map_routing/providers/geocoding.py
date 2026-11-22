"""Geocoding: place name -> boundary polygon (or point).

The engine and the area code depend only on the `Geocoder` protocol; Nominatim
is one adapter. Others (Photon, Pelias, Google, ...) can be added the same way.
"""

import hashlib
import json
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from map_routing.providers import http


class GeocodingError(RuntimeError):
    pass


@dataclass(frozen=True)
class Place:
    name: str
    geometry: BaseGeometry  # WGS84; a polygon when the provider has one, else a point
    source: str  # provider and its object id, e.g. "nominatim:relation/123"


class Geocoder(Protocol):
    def geocode(self, query: str) -> Place: ...


class NominatimGeocoder:
    """OpenStreetMap's Nominatim. Usage policy: at most 1 request per second, an
    identifying User-Agent, cache results. https://operations.osmfoundation.org/policies/nominatim/
    """

    BASE_URL = "https://nominatim.openstreetmap.org/search"
    MIN_INTERVAL_S = 1.0

    def __init__(
        self,
        cache_dir: Path,
        user_agent: str,
        fetch: Callable[[str, str], bytes] = http.get,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cache_dir = cache_dir
        self.user_agent = user_agent
        self._fetch = fetch
        self._clock = clock
        self._sleep = sleep
        self._last_request: float | None = None

    def geocode(self, query: str) -> Place:
        results = self._cached_search(query)
        if not results:
            raise GeocodingError(f"Nominatim found nothing for {query!r}")
        best = results[0]
        geometry = shape(best["geojson"])
        source = f"nominatim:{best.get('osm_type', '?')}/{best.get('osm_id', '?')}"
        return Place(name=best.get("display_name", query), geometry=geometry, source=source)

    def _cached_search(self, query: str) -> list[dict]:
        key = hashlib.sha256(query.strip().lower().encode()).hexdigest()[:16]
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text())["results"]
        results = json.loads(self._request(query))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"query": query, "results": results}))
        return results

    def _request(self, query: str) -> bytes:
        if self._last_request is not None:
            wait = self.MIN_INTERVAL_S - (self._clock() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        params = {"q": query, "format": "jsonv2", "polygon_geojson": 1, "limit": 1}
        url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
        try:
            return self._fetch(url, self.user_agent)
        finally:
            self._last_request = self._clock()

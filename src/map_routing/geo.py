"""Coordinate reference systems that work anywhere on Earth."""

import numpy as np
import shapely
from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry

WGS84 = CRS.from_epsg(4326)
# Equal-area CRS for comparing the size of large regions (e.g. Geofabrik extracts).
EQUAL_AREA = CRS.from_epsg(6933)


def utm_crs(lon: float, lat: float) -> CRS:
    """UTM zone CRS (WGS84 datum) for a point: EPSG 326xx north, 327xx south."""
    if not -180.0 <= lon <= 180.0 or not -90.0 <= lat <= 90.0:
        raise ValueError(f"not a WGS84 coordinate: lon={lon}, lat={lat}")
    zone = min(int((lon + 180.0) // 6.0) + 1, 60)
    return CRS.from_epsg((32600 if lat >= 0 else 32700) + zone)


def utm_crs_for(geometry: BaseGeometry) -> CRS:
    """UTM zone CRS chosen from a WGS84 geometry's centroid."""
    c = geometry.centroid
    return utm_crs(c.x, c.y)


def reproject(geometry: BaseGeometry, source: CRS, target: CRS) -> BaseGeometry:
    """Transform a geometry between coordinate reference systems (x = lon/easting)."""
    t = Transformer.from_crs(source, target, always_xy=True)
    return shapely.transform(geometry, lambda c: np.column_stack(t.transform(c[:, 0], c[:, 1])))

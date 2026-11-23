"""Coordinate reference systems that work anywhere on Earth."""

import numpy as np
import shapely
from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry

# Coordinate reference systems (CRS) are identified by EPSG codes, a public registry
# of coordinate systems (https://epsg.io). The codes are named once here; use the
# constants everywhere else.

# EPSG:4326, "WGS 84": longitude/latitude in degrees, the system of GPS and of all
# OpenStreetMap data. Good for storing positions, not for measuring distances or areas.
EPSG_WGS84 = 4326
WGS84 = CRS.from_epsg(EPSG_WGS84)

# EPSG:6933, "WGS 84 / NSIDC EASE-Grid 2.0 Global": an equal-area projection of the
# whole world in metres. Used to compare the size of large regions (e.g. Geofabrik
# extracts); local measurements use the area's UTM zone instead (see `utm_crs`).
EPSG_EQUAL_AREA_WORLD = 6933
EQUAL_AREA = CRS.from_epsg(EPSG_EQUAL_AREA_WORLD)

# UTM ("Universal Transverse Mercator") divides the Earth into 60 zones, 6° of
# longitude wide; within a zone, coordinates are in metres with small distortion.
# EPSG codes: 326xx for the northern hemisphere, 327xx for the southern (xx = zone).
EPSG_UTM_NORTH_BASE = 32600
EPSG_UTM_SOUTH_BASE = 32700


def utm_crs(lon: float, lat: float) -> CRS:
    """UTM zone CRS (WGS84 datum) for a point: EPSG 326xx north, 327xx south."""
    if not -180.0 <= lon <= 180.0 or not -90.0 <= lat <= 90.0:
        raise ValueError(f"not a WGS84 coordinate: lon={lon}, lat={lat}")
    zone = min(int((lon + 180.0) // 6.0) + 1, 60)
    return CRS.from_epsg((EPSG_UTM_NORTH_BASE if lat >= 0 else EPSG_UTM_SOUTH_BASE) + zone)


def utm_crs_for(geometry: BaseGeometry) -> CRS:
    """UTM zone CRS chosen from a WGS84 geometry's centroid."""
    c = geometry.centroid
    return utm_crs(c.x, c.y)


def reproject(geometry: BaseGeometry, source: CRS, target: CRS) -> BaseGeometry:
    """Transform a geometry between coordinate reference systems (x = lon/easting)."""
    t = Transformer.from_crs(source, target, always_xy=True)
    return shapely.transform(geometry, lambda c: np.column_stack(t.transform(c[:, 0], c[:, 1])))

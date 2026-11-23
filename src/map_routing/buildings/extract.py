"""Step M1b, part 1: every building in an area with its raw tags, no judgement.

Also extracts context layers the imputation rules use: residential land use
polygons and address points.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

from map_routing import osmium
from map_routing.area.model import Area
from map_routing.geo import WGS84, utm_crs_for

# Tags copied into their own columns; everything is also kept in `tags` (JSON).
TAG_COLUMNS = {
    "building": "building",
    "building:levels": "building_levels",
    "height": "height",
    "addr:street": "addr_street",
    "addr:housenumber": "addr_housenumber",
    "amenity": "amenity",
    "shop": "shop",
    "landuse": "landuse",
}
OSM_TYPE_PREFIX = {"node": "n", "way": "w", "relation": "r"}


def read_geojsonseq(path: Path) -> Iterator[dict]:
    with path.open() as f:
        for line in f:
            line = line.lstrip("\x1e").strip()  # RFC 8142 record separator
            if line:
                yield json.loads(line)


def features_to_gdf(features: Iterator[dict]) -> gpd.GeoDataFrame:
    rows, geoms = [], []
    for feat in features:
        props = dict(feat["properties"])
        osm_type, osm_id = props.pop("@type"), props.pop("@id")
        row = {"osm_id": f"{OSM_TYPE_PREFIX[osm_type]}{osm_id}"}
        row.update({col: props.get(tag) for tag, col in TAG_COLUMNS.items()})
        row["tags"] = json.dumps(props, ensure_ascii=False, sort_keys=True)
        rows.append(row)
        geoms.append(shape(feat["geometry"]))
    columns = ["osm_id", *TAG_COLUMNS.values(), "tags"]
    return gpd.GeoDataFrame(pd.DataFrame(rows, columns=columns), geometry=geoms, crs=WGS84)


def keep_matching(gdf: gpd.GeoDataFrame, column: str, value: str | None = None):
    """Rows whose tag matches the filter that selected them.

    `osmium tags-filter` also keeps objects referenced by matching relations (the
    member ways of a multipolygon building or land use area), and some of those carry
    other tags (e.g. `building:part=yes`), so they come out of the export as extra
    features. Without this check they would count as untyped buildings.
    """
    mask = gdf[column].notna() if value is None else gdf[column].eq(value)
    return gdf[mask].reset_index(drop=True)


def add_measures(gdf: gpd.GeoDataFrame, area: Area) -> gpd.GeoDataFrame:
    """Footprint area (m²) and centroid, both computed in the area's UTM zone."""
    utm = gdf.to_crs(utm_crs_for(area.geometry))
    centroids = gpd.GeoSeries(utm.geometry.centroid, crs=utm.crs).to_crs(WGS84)
    gdf = gdf.copy()
    gdf["footprint_m2"] = utm.geometry.area.round(1)
    gdf["lon"], gdf["lat"] = centroids.x.round(7), centroids.y.round(7)
    return gdf


def _export(area_dir: Path, name: str, filter_expr: str, geometry_types: str) -> Path:
    source = area_dir / "area.osm.pbf"
    filtered = area_dir / f"{name}.osm.pbf"
    seq = area_dir / f"{name}.geojsonseq"
    osmium.tags_filter(source, filtered, filter_expr)
    osmium.export_geojsonseq(filtered, seq, geometry_types)
    filtered.unlink()
    return seq


def extract_buildings(area: Area, area_dir: Path) -> tuple[Path, Path]:
    """Write buildings_raw.parquet and context.parquet; return their paths."""
    if not (area_dir / "area.osm.pbf").exists():
        raise FileNotFoundError("area.osm.pbf missing; run `map-routing area fetch` first")

    seq = _export(area_dir, "buildings", "wr/building", "polygon")
    buildings = add_measures(keep_matching(features_to_gdf(read_geojsonseq(seq)), "building"), area)
    seq.unlink()
    # The cut keeps buildings crossing the boundary whole; a building belongs to the
    # area when its centroid lies inside the boundary.
    centroids = gpd.points_from_xy(buildings.lon, buildings.lat)
    buildings = buildings[area.geometry.covers(centroids)].reset_index(drop=True)

    landuse_seq = _export(area_dir, "landuse", "wr/landuse=residential", "polygon")
    landuse = keep_matching(features_to_gdf(read_geojsonseq(landuse_seq)), "landuse", "residential")
    landuse_seq.unlink()
    landuse["kind"] = "residential_landuse"

    address_seq = _export(area_dir, "addresses", "n/addr:housenumber", "point")
    addresses = keep_matching(features_to_gdf(read_geojsonseq(address_seq)), "addr_housenumber")
    address_seq.unlink()
    addresses["kind"] = "address"

    context = gpd.GeoDataFrame(pd.concat([landuse, addresses], ignore_index=True), crs=WGS84)
    buildings_path = area_dir / "buildings_raw.parquet"
    context_path = area_dir / "context.parquet"
    buildings.to_parquet(buildings_path)
    context.to_parquet(context_path)
    return buildings_path, context_path

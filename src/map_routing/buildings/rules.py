"""Imputation rules. Each rule fills only missing values and records where every
value came from in a `<field>_source` column (plus a `<field>_reason` where useful).

Rules share one interface (`name`, `apply(buildings, ctx)`), so new ones, such as a
classifier for building types, can be added without changing the pipeline.
"""

import re
from dataclasses import dataclass
from typing import Literal, Protocol

import geopandas as gpd
import numpy as np
import pandas as pd
from pydantic import BaseModel
from pyproj import CRS
from scipy.spatial import cKDTree


class ImputationConfig(BaseModel):
    """Defaults that work for a typical European city; override per area."""

    # Building values that mean "residential" when tagged.
    residential_types: list[str] = [
        "apartments",
        "residential",
        "house",
        "detached",
        "semidetached_house",
        "terrace",
        "dormitory",
        "bungalow",
        "townhouse",
    ]
    # Amenities that make an untyped building non-residential. Shops and cafes are
    # not here: they are often on the ground floor of apartment blocks.
    excluding_amenities: list[str] = [
        "place_of_worship",
        "school",
        "college",
        "university",
        "kindergarten",
        "childcare",
        "hospital",
        "clinic",
        "parking",
        "fuel",
        "townhall",
        "police",
        "fire_station",
        "courthouse",
        "library",
        "theatre",
        "cinema",
        "prison",
        "marketplace",
        "bus_station",
        "community_centre",
        "public_building",
        "shelter",
        "car_wash",
    ]
    min_footprint_m2: float = 150.0
    max_footprint_m2: float = 5000.0
    # "auto": use residential land use only where it is mapped widely enough.
    landuse_mode: Literal["auto", "require", "ignore"] = "auto"
    landuse_min_coverage: float = 0.3
    metres_per_floor: float = 3.0
    # Neighbour medians are tried with each radius in turn (needs k observed buildings).
    neighbour_radii_m: list[float] = [300.0, 1000.0]
    neighbour_k: int = 5
    # Below this many observed buildings, the area's own distribution is not trusted.
    min_observed_for_area_distribution: int = 30
    default_floors: dict[int, float] = {1: 0.2, 2: 0.3, 3: 0.3, 4: 0.2}
    address_max_distance_m: float = 30.0
    seed: int = 0


@dataclass
class Context:
    config: ImputationConfig
    utm: CRS
    landuse: gpd.GeoDataFrame  # residential land use polygons, UTM
    addresses: gpd.GeoDataFrame  # address points, UTM
    rng: np.random.Generator
    notes: dict  # rules record decisions here (e.g. whether land use was used)


class Rule(Protocol):
    name: str

    def apply(self, buildings: gpd.GeoDataFrame, ctx: Context) -> gpd.GeoDataFrame: ...


def _points_utm(buildings: gpd.GeoDataFrame, utm: CRS) -> gpd.GeoSeries:
    return gpd.GeoSeries(gpd.points_from_xy(buildings.lon, buildings.lat), crs=4326).to_crs(utm)


class ResidentialRule:
    """Tagged type first; for untyped buildings, amenity, footprint and land use."""

    name = "residential"

    def apply(self, buildings: gpd.GeoDataFrame, ctx: Context) -> gpd.GeoDataFrame:
        cfg = ctx.config
        b = buildings.copy()
        b["residential"] = pd.NA
        b["residential_source"] = None
        b["residential_reason"] = None

        kind = b.building.str.split(";").str[0].str.strip()  # "apartments;yes" -> "apartments"
        typed = kind.ne("yes") & kind.notna()
        is_res = kind.isin(cfg.residential_types)
        b.loc[typed, ["residential", "residential_source"]] = [False, "osm"]
        b.loc[typed & is_res, "residential"] = True
        b.loc[typed, "residential_reason"] = "building=" + b.loc[typed, "building"]

        untyped = ~typed
        amen = untyped & b.amenity.isin(cfg.excluding_amenities)
        b.loc[amen, ["residential", "residential_source"]] = [False, "osm"]
        b.loc[amen, "residential_reason"] = "amenity=" + b.loc[amen, "amenity"]

        todo = untyped & ~amen
        small = todo & (b.footprint_m2 < cfg.min_footprint_m2)
        large = todo & (b.footprint_m2 > cfg.max_footprint_m2)
        b.loc[small, "residential_reason"] = f"footprint<{cfg.min_footprint_m2:g}"
        b.loc[large, "residential_reason"] = f"footprint>{cfg.max_footprint_m2:g}"
        b.loc[small | large, ["residential", "residential_source"]] = [False, "rule"]

        sized = todo & ~small & ~large
        inside = self._inside_landuse(b, ctx)
        coverage = float(inside.mean()) if len(b) else 0.0
        use_landuse = cfg.landuse_mode == "require" or (
            cfg.landuse_mode == "auto" and coverage >= cfg.landuse_min_coverage
        )
        ctx.notes["landuse_coverage"] = round(coverage, 3)
        ctx.notes["landuse_used"] = use_landuse
        if use_landuse:
            b.loc[sized & inside, "residential"] = True
            b.loc[sized & inside, "residential_reason"] = "footprint ok, residential land use"
            b.loc[sized & ~inside, "residential"] = False
            b.loc[sized & ~inside, "residential_reason"] = "outside residential land use"
        else:
            b.loc[sized, "residential"] = True
            b.loc[sized, "residential_reason"] = "footprint ok"
        b.loc[sized, "residential_source"] = "rule"
        b["residential"] = b["residential"].astype(bool)
        return b

    @staticmethod
    def _inside_landuse(b: gpd.GeoDataFrame, ctx: Context) -> pd.Series:
        if ctx.landuse.empty:
            return pd.Series(False, index=b.index)
        pts = gpd.GeoDataFrame(geometry=_points_utm(b, ctx.utm).values, index=b.index)
        joined = gpd.sjoin(pts, ctx.landuse[["geometry"]], predicate="within", how="left")
        return joined.index_right.notna().groupby(level=0).any().reindex(b.index, fill_value=False)


_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def parse_number(value: object) -> float | None:
    """First number in an OSM value such as '6', '4;5', '18 m', '2,5'."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    m = _NUMBER.search(str(value))
    return float(m.group().replace(",", ".")) if m else None


class FloorsRule:
    """building:levels, then height, then the median of nearby observed buildings
    (several radii), then the area's observed distribution, then a configured default.
    Only residential buildings get imputed floors."""

    name = "floors"

    def apply(self, buildings: gpd.GeoDataFrame, ctx: Context) -> gpd.GeoDataFrame:
        cfg = ctx.config
        b = buildings.copy()
        levels = pd.to_numeric(b.building_levels.map(parse_number), errors="coerce")
        height = pd.to_numeric(b.height.map(parse_number), errors="coerce") / cfg.metres_per_floor
        b["floors"] = np.nan
        b["floors_source"] = None

        ok_levels = levels.notna() & (levels >= 1)
        b.loc[ok_levels, "floors"] = levels[ok_levels].round().clip(lower=1)
        b.loc[ok_levels, "floors_source"] = "osm"
        ok_height = b.floors.isna() & height.notna() & (height >= 1)
        b.loc[ok_height, "floors"] = height[ok_height].round().clip(lower=1)
        b.loc[ok_height, "floors_source"] = "height"

        observed = b.floors.notna() & b.residential
        values = b.loc[observed, "floors"].to_numpy()
        if observed.any():
            xy = np.column_stack(_xy(b, ctx.utm))
            tree = cKDTree(xy[observed.to_numpy()])
            for radius in cfg.neighbour_radii_m:
                missing = (b.floors.isna() & b.residential).to_numpy()
                if not missing.any():
                    break
                k = min(cfg.neighbour_k, len(values))
                dist, idx = tree.query(xy[missing], k=k, distance_upper_bound=radius)
                dist, idx = dist.reshape(len(dist), -1), idx.reshape(len(idx), -1)
                enough = np.isfinite(dist).all(axis=1)
                if not enough.any():
                    continue
                target = b.index[missing][enough]
                b.loc[target, "floors"] = np.median(values[idx[enough]], axis=1).round()
                b.loc[target, "floors_source"] = f"neighbours_{radius:g}m"

        still = b.floors.isna() & b.residential
        if still.any() and len(values) >= cfg.min_observed_for_area_distribution:
            # The area's own observed distribution: adapts to tall city centres and villages.
            b.loc[still, "floors"] = ctx.rng.choice(values, size=int(still.sum()))
            b.loc[still, "floors_source"] = "area_distribution"
        still = b.floors.isna() & b.residential
        if still.any():
            options = np.array(list(cfg.default_floors))
            probs = np.array(list(cfg.default_floors.values()), dtype=float)
            b.loc[still, "floors"] = ctx.rng.choice(
                options, size=int(still.sum()), p=probs / probs.sum()
            )
            b.loc[still, "floors_source"] = "default"
        return b


def _xy(b: gpd.GeoDataFrame, utm: CRS) -> tuple[np.ndarray, np.ndarray]:
    pts = _points_utm(b, utm)
    return pts.x.to_numpy(), pts.y.to_numpy()


class AddressRule:
    """The building's own address tags, else the nearest address point (display only)."""

    name = "address"

    def apply(self, buildings: gpd.GeoDataFrame, ctx: Context) -> gpd.GeoDataFrame:
        b = buildings.copy()
        own = b.addr_housenumber.notna()
        street = b.addr_street.fillna("")
        b["address"] = None
        b["address_source"] = None
        b.loc[own, "address"] = (street[own] + " " + b.loc[own, "addr_housenumber"]).str.strip()
        b.loc[own, "address_source"] = "osm"

        missing = ~own
        if missing.any() and not ctx.addresses.empty:
            a = ctx.addresses
            tree = cKDTree(np.column_stack([a.geometry.x, a.geometry.y]))
            x, y = _xy(b.loc[missing], ctx.utm)
            dist, idx = tree.query(
                np.column_stack([x, y]), distance_upper_bound=ctx.config.address_max_distance_m
            )
            found = np.isfinite(dist)
            labels = (a.addr_street.fillna("") + " " + a.addr_housenumber.fillna("")).str.strip()
            target = b.index[missing.to_numpy()][found]
            b.loc[target, "address"] = labels.to_numpy()[idx[found]]
            b.loc[target, "address_source"] = "nearest_point"
        return b


DEFAULT_RULES: list[Rule] = [ResidentialRule(), FloorsRule(), AddressRule()]

"""Synthetic scenarios: one source of scenarios, sampled from an area's imputed buildings.

Real customer bases are uneven, so the default layout is a mixture of a few dense
areas of different sizes plus scattered outliers. Scenarios of different sizes are
nested: `small` is a prefix of `medium`, which is a prefix of `full`, so results
can be compared across sizes.
"""

from collections import Counter
from datetime import UTC, datetime
from typing import Literal

import geopandas as gpd
import numpy as np
from pydantic import BaseModel, model_validator
from scipy.spatial import cKDTree

from map_routing.area.model import Area
from map_routing.geo import WGS84, utm_crs_for
from map_routing.scenario.schema import WEEKDAYS, Location, Scenario, ScenarioMeta, Workforce

SIZES = {"small": 100, "medium": 300, "full": 1000}
LOADS = {
    # visits per week -> probability
    "moderate": {1: 0.30, 2: 0.45, 3: 0.20, 5: 0.05},  # mean ~2.05
    "high": {3: 0.15, 4: 0.15, 5: 0.70},  # mean ~4.55 (about 4,500 visits for 1,000 buildings)
}


class GeneratorConfig(BaseModel):
    layout: Literal["mixed", "compact"] = "mixed"
    load: Literal["moderate", "high"] = "moderate"
    n_centres: int = 3
    component_weights: list[float] = [0.50, 0.30, 0.15]  # dense areas; the rest are outliers
    component_sigma_m: list[float] = [700.0, 550.0, 450.0]  # Gaussian kernel per dense area
    compact_sigma_m: float = 1200.0
    min_centre_distance_m: float = 1500.0
    density_radius_m: float = 500.0
    workdays: list[str] = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    forbidden_day_share: float = 0.10
    base_duration_min: float = 15.0
    duration_per_floor_min: float = 3.0
    duration_noise_sd_min: float = 3.0
    duration_range_min: tuple[float, float] = (15.0, 90.0)
    shift_min: float = 480.0

    @model_validator(mode="after")
    def _consistent_components(self) -> GeneratorConfig:
        if not len(self.component_weights) == len(self.component_sigma_m) == self.n_centres:
            raise ValueError(
                f"n_centres ({self.n_centres}), component_weights "
                f"({len(self.component_weights)}) and component_sigma_m "
                f"({len(self.component_sigma_m)}) must have the same length"
            )
        if any(w < 0 for w in self.component_weights) or sum(self.component_weights) > 1:
            raise ValueError("component_weights must be >= 0 and sum to at most 1 (rest: outliers)")
        return self


def load_pool(area_dir) -> gpd.GeoDataFrame:
    path = area_dir / "buildings.parquet"
    if not path.exists():
        raise FileNotFoundError("buildings.parquet missing; run `buildings impute` first")
    b = gpd.read_parquet(path)
    return b[b.residential].reset_index(drop=True)


def _gaussian_order(rng: np.random.Generator, d2: np.ndarray, sigma: float) -> np.ndarray:
    """Weighted random order without replacement over the whole pool, with Gaussian
    weights w = exp(-d²/2σ²) (Efraimidis–Spirakis keys log(u)/w, computed in log space).
    Far away, the weights underflow; there the order falls back to nearest first, so a
    dense area never runs out of buildings."""
    with np.errstate(over="ignore"):
        keys = np.log(rng.random(len(d2))) * np.exp(d2 / (2 * sigma**2))
    return np.lexsort((d2, -keys))  # by key (largest first), ties by distance


def _choose_centres(rng, xy, density, n, min_dist) -> list[int]:
    centres: list[int] = []
    p = density / density.sum()
    for _ in range(200 * n):
        if len(centres) == n:
            break
        i = int(rng.choice(len(xy), p=p))
        if all(np.hypot(*(xy[i] - xy[c])) >= min_dist for c in centres):
            centres.append(i)
    if len(centres) < n:
        raise ValueError(f"could not place {n} centres {min_dist:g} m apart; lower n_centres")
    return centres


def sample_order(
    pool: gpd.GeoDataFrame, area: Area, cfg: GeneratorConfig, rng: np.random.Generator, n: int
) -> tuple[np.ndarray, list[str], dict]:
    """Ordered sample of n pool indices; every prefix follows the mixture weights."""
    if len(pool) < n:
        raise ValueError(f"only {len(pool)} residential buildings, need {n}")
    pts = gpd.GeoSeries(gpd.points_from_xy(pool.lon, pool.lat), crs=WGS84)
    pts = pts.to_crs(utm_crs_for(area.geometry))
    xy = np.column_stack([pts.x, pts.y])
    tree = cKDTree(xy)
    density = tree.query_ball_point(xy, cfg.density_radius_m, return_length=True).astype(float)

    if cfg.layout == "compact":
        weights, sigmas = [1.0], [cfg.compact_sigma_m]
        centres = _choose_centres(rng, xy, density, 1, 0.0)
    else:
        weights, sigmas = cfg.component_weights, cfg.component_sigma_m
        centres = _choose_centres(rng, xy, density, cfg.n_centres, cfg.min_centre_distance_m)
    outlier_weight = max(0.0, 1.0 - sum(weights))

    orders = [
        _gaussian_order(rng, ((xy - xy[c]) ** 2).sum(axis=1), sigma)
        for c, sigma in zip(centres, sigmas, strict=True)
    ]
    orders.append(rng.permutation(len(xy)))  # outliers: uniform over the pool
    probs = np.array([*weights, outlier_weight])
    probs = probs / probs.sum()

    chosen, labels, used = [], [], np.zeros(len(xy), dtype=bool)
    positions = [0] * len(orders)
    names = [f"area{i + 1}" for i in range(len(centres))] + ["outlier"]
    while len(chosen) < n:
        k = int(rng.choice(len(orders), p=probs))
        order = orders[k]
        while used[order[positions[k]]]:  # every order covers the whole pool
            positions[k] += 1
        idx = int(order[positions[k]])
        used[idx] = True
        chosen.append(idx)
        labels.append(names[k])
    centre_info = [
        {"lon": float(pool.lon.iloc[c]), "lat": float(pool.lat.iloc[c]), "sigma_m": s, "weight": w}
        for c, s, w in zip(centres, sigmas, weights, strict=True)
    ]
    return np.array(chosen), labels, {"centres": centre_info, "outlier_weight": outlier_weight}


def demand(rng: np.random.Generator, floors: np.ndarray, cfg: GeneratorConfig):
    dist = LOADS[cfg.load]
    visits = rng.choice(list(dist), size=len(floors), p=np.array(list(dist.values())))
    visits = np.minimum(visits, len(cfg.workdays))
    lo, hi = cfg.duration_range_min
    noise = rng.normal(0, cfg.duration_noise_sd_min, size=len(floors))
    duration = np.clip(cfg.base_duration_min + cfg.duration_per_floor_min * floors + noise, lo, hi)
    days = []
    forbid = rng.random(len(floors)) < cfg.forbidden_day_share
    forbidden_pick = rng.integers(0, len(cfg.workdays), size=len(floors))
    for i in range(len(floors)):
        allowed = list(cfg.workdays)
        if forbid[i] and visits[i] < len(allowed):
            allowed.pop(int(forbidden_pick[i]))
        days.append(tuple(d for d in WEEKDAYS if d in allowed))
    return visits.astype(int), duration.round().astype(float), days


def _opt(value: object) -> str | None:
    """None for missing values (parquet gives NaN or None)."""
    return None if value is None or (isinstance(value, float) and np.isnan(value)) else str(value)


def _positive(value: object) -> float | None:
    """A measurement only when it is a positive number (degenerate outlines give 0)."""
    v = float(value) if value is not None else float("nan")
    return v if v > 0 else None


def generate(area_dir, area: Area, size: str, seed: int, cfg: GeneratorConfig) -> Scenario:
    """Scenario of the given size. Always samples the full ordered set first and takes
    a prefix, so the same seed gives nested scenarios across sizes."""
    pool = load_pool(area_dir)
    rng = np.random.default_rng(seed)
    n = SIZES[size]
    if len(pool) < n:
        raise ValueError(f"only {len(pool)} residential buildings, need {n} for size {size!r}")
    # Always draw the longest possible ordered sample (up to `full`), so smaller sizes
    # are prefixes of larger ones, also in areas with fewer buildings than `full`.
    n_ordered = min(SIZES["full"], len(pool))
    order, labels, layout_info = sample_order(pool, area, cfg, rng, n_ordered)
    rows = pool.iloc[order].reset_index(drop=True)
    visits, duration, days = demand(rng, rows.floors.to_numpy(dtype=float), cfg)

    locations = [
        Location(
            id=f"b{i + 1:04d}",
            osm_id=rows.osm_id.iloc[i],
            lat=float(rows.lat.iloc[i]),
            lon=float(rows.lon.iloc[i]),
            address=_opt(rows.address.iloc[i]),
            floors=float(rows.floors.iloc[i]),
            footprint_m2=_positive(rows.footprint_m2.iloc[i]),
            floors_source=_opt(rows.floors_source.iloc[i]),
            address_source=_opt(rows.address_source.iloc[i]),
            visits_per_week=int(visits[i]),
            duration_min=float(duration[i]),
            allowed_days=days[i],
        )
        for i in range(n)
    ]
    component_counts = dict(sorted(Counter(labels[:n]).items()))
    meta = ScenarioMeta(
        name=scenario_name(area.slug, size, seed, cfg),
        area_slug=area.slug,
        area_data_date=area.data_date,
        source="synthetic",
        created=datetime.now(UTC).replace(microsecond=0),
        seed=seed,
        parameters={
            "size": size,
            "generator": cfg.model_dump(mode="json"),
            **layout_info,
            "component_counts": component_counts,
            "pool_size": len(pool),
        },
        workforce=Workforce(shift_min=cfg.shift_min),
    )
    return Scenario(meta=meta, locations=locations)


def scenario_name(slug: str, size: str, seed: int, cfg: GeneratorConfig) -> str:
    parts = [slug, size]
    if cfg.layout != "mixed":
        parts.append(cfg.layout)
    if cfg.load != "moderate":
        parts.append(cfg.load)
    return "-".join([*parts, f"s{seed}"])

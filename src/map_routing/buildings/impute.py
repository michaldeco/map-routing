"""Step M1b, part 2: run the imputation rules and summarise the data quality."""

import json
from pathlib import Path

import geopandas as gpd
import numpy as np

from map_routing.area.model import Area
from map_routing.buildings.rules import DEFAULT_RULES, Context, ImputationConfig, Rule
from map_routing.geo import utm_crs_for


def load_config(area_dir: Path, override: Path | None = None) -> ImputationConfig:
    """Defaults, overridden by `imputation.json` in the area folder or an explicit file."""
    path = override or area_dir / "imputation.json"
    if path.exists():
        return ImputationConfig.model_validate_json(path.read_text())
    return ImputationConfig()


def impute(
    buildings: gpd.GeoDataFrame,
    context: gpd.GeoDataFrame,
    area: Area,
    config: ImputationConfig,
    rules: list[Rule] = DEFAULT_RULES,
) -> tuple[gpd.GeoDataFrame, dict]:
    utm = utm_crs_for(area.geometry)
    ctx = Context(
        config=config,
        utm=utm,
        landuse=context[context.kind == "residential_landuse"].to_crs(utm),
        addresses=context[context.kind == "address"].to_crs(utm),
        rng=np.random.default_rng(config.seed),
        notes={},
    )
    for rule in rules:
        buildings = rule.apply(buildings, ctx)
    return buildings, quality_summary(buildings, ctx.notes, config)


def quality_summary(b: gpd.GeoDataFrame, notes: dict, config: ImputationConfig) -> dict:
    res = b[b.residential]

    def counts(series) -> dict:
        return {str(k): int(v) for k, v in series.value_counts(dropna=False).items()}

    return {
        "buildings": len(b),
        "residential": len(res),
        "residential_by_reason": counts(b.residential_reason.where(b.residential)),
        "excluded_by_reason": counts(b.residential_reason.where(~b.residential)),
        "floors_source (residential)": counts(res.floors_source),
        "address_source (residential)": counts(res.address_source.fillna("none")),
        "notes": notes,
        "config": config.model_dump(),
    }


def run(area_dir: Path, config: ImputationConfig) -> tuple[Path, dict]:
    area = Area.load(area_dir)
    raw = area_dir / "buildings_raw.parquet"
    if not raw.exists():
        raise FileNotFoundError("buildings_raw.parquet missing; run `buildings extract` first")
    buildings, quality = impute(
        gpd.read_parquet(raw), gpd.read_parquet(area_dir / "context.parquet"), area, config
    )
    out = area_dir / "buildings.parquet"
    buildings.to_parquet(out)
    (area_dir / "quality.json").write_text(json.dumps(quality, indent=2) + "\n")
    return out, quality

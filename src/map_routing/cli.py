"""Command-line interface: `map-routing area|buildings|scenario ...`."""

from pathlib import Path
from typing import Annotated

import typer

from map_routing.settings import load_settings

app = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help="Visit scheduling and routing on OpenStreetMap data.",
)
area_app = typer.Typer(no_args_is_help=True, help="Define areas and fetch their map data.")
buildings_app = typer.Typer(no_args_is_help=True, help="Extract and impute buildings.")
scenario_app = typer.Typer(no_args_is_help=True, help="Generate and validate scenarios.")
app.add_typer(area_app, name="area")
app.add_typer(buildings_app, name="buildings")
app.add_typer(scenario_app, name="scenario")


@area_app.command("define")
def area_define(
    slug: Annotated[str, typer.Argument(help="Short name, e.g. thessaloniki")],
    bbox: Annotated[str | None, typer.Option(help="W,S,E,N in degrees")] = None,
    polygon: Annotated[Path | None, typer.Option(help="GeoJSON file with the boundary")] = None,
    place: Annotated[str | None, typer.Option(help="Place name, resolved with Nominatim")] = None,
    name: Annotated[str | None, typer.Option(help="Display name (default: slug)")] = None,
) -> None:
    """Define an area by a bounding box, a polygon file or a place name."""
    from map_routing.area.model import AreaDefinition, make_area, parse_bbox, read_polygon_file

    given = [x for x in (bbox, polygon, place) if x is not None]
    if len(given) != 1:
        raise typer.BadParameter("give exactly one of --bbox, --polygon, --place")
    settings = load_settings()
    if bbox is not None:
        geometry, definition = parse_bbox(bbox), AreaDefinition(kind="bbox", value=bbox)
    elif polygon is not None:
        geometry = read_polygon_file(polygon)
        definition = AreaDefinition(kind="polygon", value=polygon.name)
    else:
        from map_routing.providers.geocoding import NominatimGeocoder

        geocoder = NominatimGeocoder(settings.cache_dir / "nominatim", settings.user_agent)
        found = geocoder.geocode(place)
        if found.geometry.geom_type not in ("Polygon", "MultiPolygon"):
            raise typer.BadParameter(f"{place!r} has no boundary polygon; use --bbox instead")
        geometry = found.geometry
        definition = AreaDefinition(kind="place", value=place, source=found.source)
        name = name or found.name
    area = make_area(slug, name or slug, definition, geometry)
    path = area.save(settings.area_dir(slug))
    typer.echo(f"Saved {path}")


@area_app.command("fetch")
def area_fetch(
    slug: str,
    refresh: Annotated[bool, typer.Option(help="Download the extract again")] = False,
) -> None:
    """Download the smallest Geofabrik extract covering the area and cut the area out."""
    from map_routing.area.extracts import fetch_area
    from map_routing.area.model import Area

    settings = load_settings()
    area_dir = settings.area_dir(slug)
    area = Area.load(area_dir)
    target = fetch_area(
        area, area_dir, settings.cache_dir / "geofabrik", settings.user_agent, refresh=refresh
    )
    typer.echo(f"Extract {area.source_extract.id} (data {area.data_date}) -> {target}")


@buildings_app.command("extract")
def buildings_extract(slug: str) -> None:
    """Extract every building (raw tags) and context layers from the area's map data."""
    import geopandas as gpd

    from map_routing.area.model import Area
    from map_routing.buildings.extract import extract_buildings

    settings = load_settings()
    area_dir = settings.area_dir(slug)
    buildings_path, context_path = extract_buildings(Area.load(area_dir), area_dir)
    buildings = gpd.read_parquet(buildings_path)
    context = gpd.read_parquet(context_path)
    typer.echo(f"{len(buildings):,} buildings -> {buildings_path}")
    for kind, n in context["kind"].value_counts().items():
        typer.echo(f"{n:,} {kind} -> {context_path}")


@buildings_app.command("impute")
def buildings_impute(
    slug: str,
    config: Annotated[Path | None, typer.Option(help="Imputation config (JSON)")] = None,
) -> None:
    """Fill missing values with explicit rules; write buildings.parquet and quality.json."""
    from map_routing.buildings.impute import load_config, run

    area_dir = load_settings().area_dir(slug)
    out, q = run(area_dir, load_config(area_dir, config))
    typer.echo(f"{q['buildings']:,} buildings, {q['residential']:,} residential -> {out}")
    notes = q["notes"]
    typer.echo(
        f"Residential land use covers {notes['landuse_coverage']:.0%} of buildings; "
        f"used: {notes['landuse_used']}"
    )
    for title in (
        "residential_by_reason",
        "excluded_by_reason",
        "floors_source (residential)",
        "address_source (residential)",
    ):
        typer.echo(f"\n{title}:")
        items = [(k, n) for k, n in q[title].items() if k not in ("None", "nan", "<NA>")]
        for key, n in items[:10]:
            typer.echo(f"  {n:>8,}  {key}")
        if len(items) > 10:
            rest = sum(n for _, n in items[10:])
            typer.echo(f"  {rest:>8,}  ({len(items) - 10} other reasons, see quality.json)")


@scenario_app.command("validate")
def scenario_validate(path: Path) -> None:
    """Check a scenario folder against the format (and its area boundary, if defined)."""
    from pydantic import ValidationError

    from map_routing.area.model import Area
    from map_routing.scenario.io import read_scenario
    from map_routing.scenario.schema import outside

    try:
        scenario = read_scenario(path)
    except ValidationError as exc:
        typer.echo(f"Invalid scenario:\n{exc}", err=True)
        raise typer.Exit(1) from exc
    area_dir = load_settings().area_dir(scenario.meta.area_slug)
    if (area_dir / "area.json").exists():
        bad = outside(scenario, Area.load(area_dir).geometry)
        if bad:
            typer.echo(f"{len(bad)} location(s) outside the area, e.g. {bad[:5]}", err=True)
            raise typer.Exit(1)
    else:
        typer.echo(f"Area {scenario.meta.area_slug!r} not defined here; boundary not checked")
    typer.echo(
        f"OK: {len(scenario.locations):,} locations, "
        f"{scenario.visits_per_week:,} visits per week"
    )


@scenario_app.command("generate")
def scenario_generate(
    slug: str,
    size: Annotated[str, typer.Option(help="small (100), medium (300) or full (1,000)")] = "small",
    seed: Annotated[int, typer.Option(help="Random seed; same seed gives nested sizes")] = 1,
    layout: Annotated[
        str, typer.Option(help="mixed (dense areas + outliers) or compact")
    ] = "mixed",
    load: Annotated[
        str, typer.Option(help="moderate (~2 visits/week) or high (~4.5)")
    ] = "moderate",
) -> None:
    """Generate a synthetic scenario from the area's imputed buildings."""
    from map_routing.area.model import Area
    from map_routing.scenario.io import write_scenario
    from map_routing.synthetic.generator import SIZES, GeneratorConfig, generate

    if size not in SIZES:
        raise typer.BadParameter(f"size must be one of {list(SIZES)}")
    settings = load_settings()
    area_dir = settings.area_dir(slug)
    cfg = GeneratorConfig(layout=layout, load=load)
    scenario = generate(area_dir, Area.load(area_dir), size, seed, cfg)
    out = write_scenario(scenario, settings.scenarios_dir / scenario.meta.name)
    counts = scenario.meta.parameters["component_counts"]
    typer.echo(
        f"{len(scenario.locations):,} locations, {scenario.visits_per_week:,} visits "
        f"per week -> {out}"
    )
    typer.echo("  " + ", ".join(f"{k}: {v}" for k, v in counts.items()))

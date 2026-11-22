"""Command-line interface: `map-routing area|buildings|instance ...`."""

from pathlib import Path
from typing import Annotated

import typer

from map_routing.settings import load_settings

app = typer.Typer(no_args_is_help=True, help="Visit scheduling and routing on OpenStreetMap data.")
area_app = typer.Typer(no_args_is_help=True, help="Define areas and fetch their map data.")
buildings_app = typer.Typer(no_args_is_help=True, help="Extract and impute buildings.")
instance_app = typer.Typer(no_args_is_help=True, help="Generate and validate instances.")
app.add_typer(area_app, name="area")
app.add_typer(buildings_app, name="buildings")
app.add_typer(instance_app, name="instance")


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

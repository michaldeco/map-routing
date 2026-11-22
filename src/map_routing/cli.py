"""Command-line interface: `map-routing area|buildings|instance ...`."""

import typer

app = typer.Typer(no_args_is_help=True, help="Visit scheduling and routing on OpenStreetMap data.")
area_app = typer.Typer(no_args_is_help=True, help="Define areas and fetch their map data.")
buildings_app = typer.Typer(no_args_is_help=True, help="Extract and impute buildings.")
instance_app = typer.Typer(no_args_is_help=True, help="Generate and validate instances.")
app.add_typer(area_app, name="area")
app.add_typer(buildings_app, name="buildings")
app.add_typer(instance_app, name="instance")

"""Thin wrapper around the osmium command-line tool."""

import json
import shutil
import subprocess
from pathlib import Path


class OsmiumError(RuntimeError):
    pass


def available() -> bool:
    return shutil.which("osmium") is not None


def run(*args: str | Path) -> str:
    """Run `osmium <args>` and return its standard output."""
    if not available():
        raise OsmiumError("osmium is not installed (Fedora: dnf install osmium-tool)")
    cmd = ["osmium", *map(str, args)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise OsmiumError(f"{' '.join(cmd)} failed:\n{proc.stderr.strip()}")
    return proc.stdout


def fileinfo(path: Path) -> dict:
    return json.loads(run("fileinfo", "--json", path))


def data_timestamp(path: Path) -> str | None:
    """Data date from the file header (Geofabrik extracts carry it; cut files do not)."""
    options = fileinfo(path).get("header", {}).get("option", {})
    return options.get("osmosis_replication_timestamp") or options.get("timestamp")


def extract(source: Path, polygon_geojson: Path, target: Path) -> None:
    """Cut an area out of a bigger file. The `smart` strategy keeps multipolygon
    relations (large buildings, land use) complete across the boundary."""
    target.parent.mkdir(parents=True, exist_ok=True)
    run(
        "extract",
        "--polygon",
        polygon_geojson,
        "--strategy",
        "smart",
        "--overwrite",
        "-o",
        target,
        source,
    )


def tags_filter(source: Path, target: Path, *expressions: str) -> None:
    run("tags-filter", "--overwrite", "-o", target, source, *expressions)


def export_geojsonseq(source: Path, target: Path, geometry_types: str) -> None:
    """Export as GeoJSON sequence. `geometry_types` e.g. "polygon" or "point";
    without it, closed ways would come out both as lines and as polygons."""
    run(
        "export",
        "--overwrite",
        "-f",
        "geojsonseq",
        f"--geometry-types={geometry_types}",
        "-a",
        "type,id",
        "-o",
        target,
        source,
    )

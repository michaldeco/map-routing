"""Interactive HTML maps for checking generated data by eye.

`scenario_map` shows a scenario's locations by dense area; `buildings_map` shows an
area's imputed buildings by imputation result. Both are standalone Leaflet maps
(via folium); open the HTML file in a browser.

Background tiles: OpenStreetMap. Its tile servers refuse pages opened directly from a
file (their usage policy requires a Referer header, which `file://` pages do not
send), so open the maps with `map-routing view <file>`, which serves them from
http://127.0.0.1 and opens the browser.
"""

import contextlib
import functools
import urllib.parse
import webbrowser
from collections.abc import Sequence
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import mapping

from map_routing.area.model import Area
from map_routing.scenario.schema import Scenario

# Distinct colours for categories (colour-blind friendly "Tableau 10" palette).
PALETTE = [
    "#4e79a7",
    "#f28e2b",
    "#59a14f",
    "#e15759",
    "#76b7b2",
    "#edc948",
    "#b07aa1",
    "#ff9da7",
    "#9c755f",
    "#bab0ac",
]
OTHER_COLOUR = "#7f7f7f"
# Ordered values (e.g. floor bands) get a light-to-dark scale instead of distinct colours.
FLOOR_BANDS = {
    "1–2 floors": "#fdd49e",
    "3–4 floors": "#fc8d59",
    "5–6 floors": "#e34a33",
    "7–9 floors": "#b30000",
    "10+ floors": "#4a0000",
    "unknown": OTHER_COLOUR,
}
OUTLIER_COLOUR = "#222222"
# Above this many points, browsers get slow; `buildings_map` samples by default.
DEFAULT_MAX_POINTS = 5000
TILES = "OpenStreetMap"  # needs http(s) pages: see `view` below and the module docstring


def _base_map(area: Area) -> folium.Map:
    minx, miny, maxx, maxy = area.geometry.bounds
    m = folium.Map(tiles=TILES, prefer_canvas=True, control_scale=True)
    m.fit_bounds([[miny, minx], [maxy, maxx]])
    folium.GeoJson(
        mapping(area.geometry),
        name=f"Area: {area.name}",
        style_function=lambda _: {"color": "#333", "weight": 2, "fill": False, "dashArray": "6"},
    ).add_to(m)
    return m


def category_colours(categories: Sequence[str], top: int = len(PALETTE)) -> dict[str, str]:
    """Colours for the most frequent categories; the rest share OTHER_COLOUR."""
    counts = pd.Series(list(categories)).value_counts()
    return {c: PALETTE[i] if i < top else OTHER_COLOUR for i, c in enumerate(counts.index)}


def _legend(title: str, items: list[tuple[str, str, int]]) -> folium.Element:
    rows = "".join(
        f'<div><span style="display:inline-block;width:11px;height:11px;border-radius:50%;'
        f'background:{colour};margin-right:6px"></span>{label} ({n:,})</div>'
        for label, colour, n in items
    )
    html = (
        '<div style="position:fixed;bottom:48px;left:12px;z-index:9999;background:white;'
        "padding:8px 10px;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3);"
        f'font:12px/1.5 sans-serif"><b>{title}</b>{rows}</div>'
    )
    return folium.Element(html)


def _popup(fields: dict[str, object]) -> str:
    rows = "".join(
        f"<tr><th style='text-align:left;padding-right:8px'>{k}</th><td>{v}</td></tr>"
        for k, v in fields.items()
        if v is not None and not (isinstance(v, float) and np.isnan(v))
    )
    return f"<table style='font:12px sans-serif'>{rows}</table>"


def scenario_map(scenario: Scenario, area: Area) -> folium.Map:
    """Locations coloured by dense area (synthetic scenarios), sized by visits per week,
    with each dense area's centre and its 1σ/2σ circles."""
    m = _base_map(area)
    groups: dict[str, list] = {}
    for loc in scenario.locations:
        groups.setdefault(loc.component or "location", []).append(loc)
    names = sorted(groups, key=lambda g: (g == "outlier", g))
    colours = {
        g: (OUTLIER_COLOUR if g == "outlier" else PALETTE[i % len(PALETTE)])
        for i, g in enumerate(names)
    }

    for name in names:
        layer = folium.FeatureGroup(name=f"{name} ({len(groups[name]):,})")
        for loc in groups[name]:
            popup = _popup(
                {
                    "id": loc.id,
                    "group": loc.component,
                    "address": loc.address,
                    "floors": f"{loc.floors:g} ({loc.floors_source})" if loc.floors else None,
                    "footprint": f"{loc.footprint_m2:,.0f} m²" if loc.footprint_m2 else None,
                    "visits/week": loc.visits_per_week,
                    "duration": f"{loc.duration_min:g} min",
                    "allowed days": " ".join(loc.allowed_days),
                    "OSM": loc.osm_id,
                }
            )
            folium.CircleMarker(
                [loc.lat, loc.lon],
                radius=2 + 1.5 * loc.visits_per_week,
                color=colours[name],
                weight=1,
                fill=True,
                fill_opacity=0.75,
                popup=folium.Popup(popup, max_width=320),
                tooltip=f"{loc.id}: {loc.visits_per_week}×/week",
            ).add_to(layer)
        layer.add_to(m)

    centres = scenario.meta.parameters.get("centres", [])
    if centres:
        layer = folium.FeatureGroup(name="Dense area centres (1σ, 2σ)")
        for i, c in enumerate(centres):
            colour = colours.get(f"area{i + 1}", OTHER_COLOUR)
            for k in (1, 2):
                folium.Circle(
                    [c["lat"], c["lon"]],
                    radius=k * c["sigma_m"],
                    color=colour,
                    weight=2 if k == 1 else 1,
                    fill=False,
                    dash_array=None if k == 1 else "4",
                ).add_to(layer)
            folium.Marker(
                [c["lat"], c["lon"]],
                tooltip=f"area{i + 1}: weight {c['weight']:.0%}, σ = {c['sigma_m']:g} m",
            ).add_to(layer)
        layer.add_to(m)

    title = (
        f"{scenario.meta.name}: {len(scenario.locations):,} locations, "
        f"{scenario.visits_per_week:,} visits/week"
    )
    items = [(n, colours[n], len(groups[n])) for n in names]
    m.get_root().html.add_child(_legend(title, items))
    folium.LayerControl(collapsed=False).add_to(m)
    return m


def sample_buildings(
    buildings: gpd.GeoDataFrame, sample: int | None, seed: int
) -> tuple[gpd.GeoDataFrame, int]:
    """A random sample of at most `sample` buildings (None: all). Returns it and the total."""
    total = len(buildings)
    if sample is None or sample >= total:
        return buildings, total
    return buildings.sample(n=sample, random_state=seed), total


COLOUR_BY = {
    "residential": "residential",
    "reason": "residential_reason",
    "floors-source": "floors_source",
    "floors": "floors",
}


def buildings_map(
    buildings: gpd.GeoDataFrame,
    area: Area,
    colour_by: str = "reason",
    sample: int | None = DEFAULT_MAX_POINTS,
    seed: int = 0,
    residential_only: bool = False,
) -> folium.Map:
    """Imputed buildings as dots at their centroids, coloured by an imputation result."""
    if colour_by not in COLOUR_BY:
        raise ValueError(f"colour_by must be one of {list(COLOUR_BY)}")
    b = buildings[buildings.residential] if residential_only else buildings
    shown, total = sample_buildings(b, sample, seed)
    column = COLOUR_BY[colour_by]
    if colour_by == "floors":
        values = shown.floors.map(lambda f: "unknown" if pd.isna(f) else _floor_band(f))
        colours = FLOOR_BANDS
    elif colour_by == "residential":
        values = shown.residential.map({True: "residential", False: "excluded"})
    else:
        values = shown[column].fillna("none").astype(str)
    if colour_by != "floors":
        colours = category_colours(values)

    m = _base_map(area)
    for (_, row), value in zip(shown.iterrows(), values, strict=True):
        popup = _popup(
            {
                "OSM": row.osm_id,
                "building": row.building,
                "residential": row.residential,
                "reason": row.residential_reason,
                "footprint": f"{row.footprint_m2:,.0f} m²",
                "floors": f"{row.floors:g} ({row.floors_source})" if pd.notna(row.floors) else None,
                "address": row.address,
            }
        )
        folium.CircleMarker(
            [row.lat, row.lon],
            radius=3,
            color=colours[value],
            weight=0.5,
            fill=True,
            fill_opacity=0.8,
            popup=folium.Popup(popup, max_width=320),
            tooltip=value,
        ).add_to(m)

    counts = values.value_counts()
    if colour_by == "floors":  # natural order, not by frequency
        counts = counts.reindex([b for b in FLOOR_BANDS if b in counts.index])
    top = [(v, colours[v], int(n)) for v, n in counts.items() if colours[v] != OTHER_COLOUR]
    rest = int(counts[[v for v in counts.index if colours[v] == OTHER_COLOUR]].sum())
    if rest:
        top.append(("other", OTHER_COLOUR, rest))
    what = "residential buildings" if residential_only else "buildings"
    shown_text = f"{len(shown):,} of {total:,} {what}" + (
        " (random sample)" if len(shown) < total else ""
    )
    m.get_root().html.add_child(_legend(f"{area.name}: {shown_text}, by {colour_by}", top))
    return m


def _floor_band(floors: float) -> str:
    if floors <= 2:
        return "1–2 floors"
    if floors <= 4:
        return "3–4 floors"
    if floors <= 6:
        return "5–6 floors"
    if floors <= 9:
        return "7–9 floors"
    return "10+ floors"


def make_server(file: Path, port: int = 8765) -> tuple[ThreadingHTTPServer, str]:
    """HTTP server for the file's folder on 127.0.0.1 (port 0: any free port), and the
    file's URL. Only localhost can connect."""
    file = file.resolve()
    handler = functools.partial(_QuietHandler, directory=str(file.parent))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    return server, f"http://127.0.0.1:{server.server_port}/{urllib.parse.quote(file.name)}"


def view(file: Path, port: int = 8765, open_browser: bool = True) -> None:
    """Serve the map and open it in a browser; runs until interrupted (Ctrl-C)."""
    server, url = make_server(file, port)
    with server:
        print(f"Serving {url}  (Ctrl-C to stop)")
        if open_browser:
            webbrowser.open(url)
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever()


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass

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
import errno
import functools
import html
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
from map_routing.legends import (
    BUILDINGS_FOOTER as FOOTER,
)
from map_routing.legends import (
    COLOUR_BY,
    COLOUR_BY_SUBTITLE,
    MISSING_COMPONENTS_NOTE,
    SCENARIO_SUBTITLE,
    dense_areas,
    describe_group,
    explain,
    missing_components,
    sample_buildings,
)
from map_routing.legends import area_number as _area_number
from map_routing.legends import floor_band as _floor_band
from map_routing.scenario.schema import Scenario

__all__ = ["COLOUR_BY", "explain", "missing_components", "sample_buildings"]

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
FLOOR_BAND_COLOURS = {
    "1–2 floors": "#fdd49e",
    "3–4 floors": "#fc8d59",
    "5–6 floors": "#e34a33",
    "7–9 floors": "#b30000",
    "10+ floors": "#4a0000",
    "unknown": "#c7c7c7",  # its own light grey, distinct from OTHER_COLOUR
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
        name=f"Area: {html.escape(area.name)}",
        style_function=lambda _: {"color": "#333", "weight": 2, "fill": False, "dashArray": "6"},
    ).add_to(m)
    return m


def category_colours(categories: Sequence[str], top: int = len(PALETTE)) -> dict[str, str]:
    """Colours for the most frequent categories; the rest share OTHER_COLOUR."""
    counts = pd.Series(list(categories)).value_counts()
    return {c: PALETTE[i] if i < top else OTHER_COLOUR for i, c in enumerate(counts.index)}


# All text shown on a map is escaped: values come from OpenStreetMap, which anyone can
# edit, and folium inserts popups, tooltips and legends into the page as HTML.


LegendItem = tuple[str, str, int, str]  # label, colour, count, plain-language explanation


def _legend(
    title: str, items: list[LegendItem], subtitle: str = "", note: str = "", footer: str = ""
) -> folium.Element:
    """A legend that explains itself: what the colours mean (subtitle), one line of
    plain language under each entry, and how to use the map (footer)."""
    small = "font-size:11px;color:#555"
    rows = "".join(
        f'<div style="margin-top:4px"><span style="display:inline-block;width:11px;'
        f"height:11px;border-radius:50%;background:{colour};margin-right:6px;"
        f'vertical-align:-1px"></span><b>{html.escape(label)}</b> ({n:,})'
        + (f'<div style="{small};margin-left:17px">{html.escape(desc)}</div>' if desc else "")
        + "</div>"
        for label, colour, n, desc in items
    )
    parts = [f"<b>{html.escape(title)}</b>"]
    if subtitle:
        parts.append(f'<div style="{small}">{html.escape(subtitle)}</div>')
    parts.append(rows)
    if note:
        parts.append(f'<div style="color:#b00;margin-top:6px">{html.escape(note)}</div>')
    if footer:
        parts.append(f'<div style="{small};margin-top:6px">{html.escape(footer)}</div>')
    page = (
        '<div style="position:fixed;bottom:48px;left:12px;z-index:9999;background:white;'
        "padding:8px 10px;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3);"
        f'font:12px/1.5 sans-serif;max-width:360px;max-height:70vh;overflow-y:auto">'
        f'{"".join(parts)}</div>'
    )
    return folium.Element(page)


def _popup(fields: dict[str, object]) -> str:
    rows = "".join(
        f"<tr><th style='text-align:left;padding-right:8px'>{html.escape(str(k))}</th>"
        f"<td>{html.escape(str(v))}</td></tr>"
        for k, v in fields.items()
        if v is not None and not (isinstance(v, float) and np.isnan(v))
    )
    return f"<table style='font:12px sans-serif'>{rows}</table>"


def group_colour(i: int) -> str:
    """Palette colours first; beyond them, hues spread by the golden angle, so even
    many groups stay distinguishable instead of repeating."""
    if i < len(PALETTE):
        return PALETTE[i]
    return f"hsl({(i * 137.5) % 360:.0f}, 65%, 45%)"


def scenario_map(scenario: Scenario, area: Area) -> folium.Map:
    """Locations coloured by dense area (synthetic scenarios), sized by visits per week,
    with each dense area's centre and its 1σ/2σ circles."""
    m = _base_map(area)
    groups: dict[str, list] = {}
    for loc in scenario.locations:
        groups.setdefault(loc.component or "location", []).append(loc)
    names = sorted(groups, key=lambda g: (g == "outlier", _area_number(g), g))
    colours = {
        g: (OUTLIER_COLOUR if g == "outlier" else group_colour(i)) for i, g in enumerate(names)
    }

    # Centres first, so the buildings are drawn (and receive the mouse) on top.
    centres = dense_areas(scenario)
    if centres:
        layer = folium.FeatureGroup(name="Dense area centres and spread")
        for c in centres:
            colour = colours.get(c.component, OTHER_COLOUR)
            for k in (1, 2):
                folium.Circle(
                    [c.lat, c.lon],
                    radius=k * c.sigma_m,
                    color=colour,
                    weight=2 if k == 1 else 1,
                    fill=False,
                    dash_array=None if k == 1 else "4",
                    # Outlines only: never take mouse events. On a canvas map, Leaflet
                    # hit-tests a circle's whole disc even without fill, which would hide
                    # the tooltips of every building inside.
                    interactive=False,
                ).add_to(layer)
            folium.Marker(
                [c.lat, c.lon],
                tooltip=(
                    f"{c.component}: about {c.weight:.0%} of buildings, "
                    f"typical spread {c.sigma_m:,.0f} m"
                ),
            ).add_to(layer)
        layer.add_to(m)

    for name in names:
        layer = folium.FeatureGroup(name=html.escape(f"{name} ({len(groups[name]):,})"))
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
                tooltip=html.escape(f"{loc.id}: {loc.visits_per_week}×/week"),
            ).add_to(layer)
        layer.add_to(m)

    title = (
        f"{scenario.meta.name}: {len(scenario.locations):,} locations, "
        f"{scenario.visits_per_week:,} visits/week"
    )
    items = [(n, colours[n], len(groups[n]), describe_group(n, centres)) for n in names]
    note = MISSING_COMPONENTS_NOTE if missing_components(scenario) else ""
    subtitle = SCENARIO_SUBTITLE
    m.get_root().html.add_child(_legend(title, items, subtitle=subtitle, note=note, footer=FOOTER))
    folium.LayerControl(collapsed=False).add_to(m)
    return m


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
        colours = FLOOR_BAND_COLOURS
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
            tooltip=html.escape(value),
        ).add_to(m)

    counts = values.value_counts()
    if colour_by == "floors":  # natural order, not by frequency
        counts = counts.reindex([b for b in FLOOR_BAND_COLOURS if b in counts.index])
    if colour_by == "floors":  # every band, incl. "unknown", keeps its own row
        top = [(v, colours[v], int(n), explain(colour_by, v)) for v, n in counts.items()]
    else:
        top = [
            (v, colours[v], int(n), explain(colour_by, v))
            for v, n in counts.items()
            if colours[v] != OTHER_COLOUR
        ]
        rest = int(counts[[v for v in counts.index if colours[v] == OTHER_COLOUR]].sum())
        if rest:
            top.append(("other", OTHER_COLOUR, rest, explain(colour_by, "other")))
    what = "residential buildings" if residential_only else "buildings"
    shown_text = f"{len(shown):,} of {total:,} {what}" + (
        " (random sample)" if len(shown) < total else ""
    )
    legend = _legend(
        f"{area.name}: {shown_text}",
        top,
        subtitle=COLOUR_BY_SUBTITLE[colour_by],
        footer=FOOTER,
    )
    m.get_root().html.add_child(legend)
    return m


def make_server(file: Path, port: int = 8765) -> tuple[ThreadingHTTPServer, str]:
    """HTTP server for the file's folder on 127.0.0.1 (port 0: any free port), and the
    file's URL. Only localhost can connect."""
    file = file.resolve()
    handler = functools.partial(_QuietHandler, directory=str(file.parent))
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        # e.g. another `view` is still running: take any free port instead
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
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

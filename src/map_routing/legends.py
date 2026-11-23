"""Plain-language legend content for map views, shared by every renderer.

What a colouring means, one explanation per category, display order and the
grouping of values: defined here once, without any colours. The API sends this
to the web app; colours are a presentation decision of the frontend.
"""

import re

import geopandas as gpd
import pandas as pd

from map_routing.scenario.schema import Scenario

# Building colourings: option name -> column in buildings.parquet.
COLOUR_BY = {
    "residential": "residential",
    "reason": "residential_reason",
    "floors-source": "floors_source",
    "floors": "floors",
}

# What each colouring shows (legend subtitle).
COLOUR_BY_SUBTITLE = {
    "residential": "Colour: does the building count as residential (a possible customer)?",
    "reason": "Colour: why the building counts as residential or not.",
    "floors-source": "Colour: where the building's number of floors comes from.",
    "floors": "Colour: number of floors, from OpenStreetMap or estimated.",
}

BUILDINGS_FOOTER = (
    "Each dot is one building (at its centre). Hover for a summary, click for details."
)
SCENARIO_SUBTITLE = (
    "Colour: how the generator picked the building. Dot size: visits per week. "
    "Dense areas have no edge: picks get rarer with distance from the centre, so "
    "some lie outside the circles."
)
SCENARIO_FOOTER = BUILDINGS_FOOTER
MISSING_COMPONENTS_NOTE = (
    "This scenario has no dense-area labels (generated before they were recorded); "
    "regenerate it with `map-routing scenario generate` to colour the dense areas."
)

# Floor bands in display order; "unknown" for buildings without floors.
FLOOR_BANDS = ["1–2 floors", "3–4 floors", "5–6 floors", "7–9 floors", "10+ floors", "unknown"]


def floor_band(floors: float) -> str:
    floors = round(floors)  # imputed floors are whole numbers already; be safe for others
    if floors <= 2:
        return "1–2 floors"
    if floors <= 4:
        return "3–4 floors"
    if floors <= 6:
        return "5–6 floors"
    if floors <= 9:
        return "7–9 floors"
    return "10+ floors"


def categories(buildings: gpd.GeoDataFrame, colour_by: str) -> pd.Series:
    """The legend category of each building for a colouring, as text."""
    if colour_by not in COLOUR_BY:
        raise ValueError(f"colour_by must be one of {list(COLOUR_BY)}")
    if colour_by == "floors":
        return buildings.floors.map(lambda f: "unknown" if pd.isna(f) else floor_band(f))
    if colour_by == "residential":
        return buildings.residential.map({True: "residential", False: "excluded"})
    return buildings[COLOUR_BY[colour_by]].fillna("none").astype(str)


# Most categories a legend shows before grouping the rest into "other".
MAX_CATEGORIES = 10


def group_rare(values: pd.Series, colour_by: str, top: int = MAX_CATEGORIES) -> pd.Series:
    """Keep the `top` most frequent categories; the rest become "other". Floor bands
    are never grouped (there are few and their order matters)."""
    if colour_by == "floors":
        return values
    keep = set(values.value_counts().index[:top])
    return values.where(values.isin(keep), "other")


def ordered_counts(values: pd.Series, colour_by: str) -> list[tuple[str, int]]:
    """(category, count) in display order: floor bands in natural order, all other
    colourings by frequency."""
    counts = values.value_counts()
    if colour_by == "floors":
        counts = counts.reindex([b for b in FLOOR_BANDS if b in counts.index])
    items = [(str(v), int(n)) for v, n in counts.items() if v != "other"]
    if "other" in counts.index:  # grouped rare values always come last
        items.append(("other", int(counts["other"])))
    return items


def explain(colour_by: str, value: str) -> str:
    """One plain-language line for a legend entry."""
    if value == "other":
        return "less frequent values, grouped together"
    if colour_by == "residential":
        return {
            "residential": "counts as a home; can appear in scenarios",
            "excluded": "not a home (other use, too small or too large)",
        }.get(value, "")
    if colour_by == "reason":
        return _explain_reason(value)
    if colour_by == "floors-source":
        return _explain_floors_source(value)
    if colour_by == "floors":
        return (
            "no number of floors (only residential buildings get estimates)"
            if value == "unknown"
            else ""
        )
    return ""


def _explain_reason(value: str) -> str:
    if value.startswith("building="):
        return f"OpenStreetMap names its type: {value.removeprefix('building=')}"
    if value.startswith("amenity="):
        use = value.removeprefix("amenity=").replace("_", " ")
        return f"type not named, but used as: {use} (not a home)"
    if m := re.fullmatch(r"footprint<(\d+(?:\.\d+)?)", value):
        return f"type not named; ground area under {m.group(1)} m² (shed, garage, kiosk)"
    if m := re.fullmatch(r"footprint>(\d+(?:\.\d+)?)", value):
        return f"type not named; ground area over {m.group(1)} m² (hall, mall, factory)"
    return {
        "footprint ok, residential land use": (
            "type not named; usual size, inside a residential zone"
        ),
        "outside residential land use": (
            "type not named; usual size, but outside residential zones"
        ),
        "footprint ok": (
            "type not named; usual size (residential zones are mapped too sparsely to use)"
        ),
    }.get(value, "")


def _explain_floors_source(value: str) -> str:
    if m := re.fullmatch(r"neighbours_(\d+)m", value):
        return (
            "estimated: typical floors of nearby buildings with known floors "
            f"(within {m.group(1)} m)"
        )
    return {
        "osm": "known: tagged in OpenStreetMap",
        "height": "estimated from the tagged height (about 3 m per floor)",
        "area_median": "estimated: no known buildings nearby, so the area's typical value",
        "area_distribution": (
            "estimated: no known buildings nearby, so a random value typical for the area"
        ),
        "default_median": (
            "estimated: too few known buildings in the area, so a configured default"
        ),
        "default_distribution": (
            "estimated: too few known buildings in the area, so a random default"
        ),
        "none": "no estimate (not a residential building)",
    }.get(value, "")


def area_number(group: str) -> int:
    """1 for "area1" etc.; a large number for anything else (sorts last)."""
    m = re.fullmatch(r"area(\d+)", group)
    return int(m.group(1)) if m else 10**9


def scenario_groups(scenario: Scenario) -> list[tuple[str, int]]:
    """(group, count) in display order: area1, area2, ..., other labels, outlier last."""
    counts: dict[str, int] = {}
    for loc in scenario.locations:
        group = loc.component or "location"
        counts[group] = counts.get(group, 0) + 1
    order = sorted(counts, key=lambda g: (g == "outlier", area_number(g), g))
    return [(g, counts[g]) for g in order]


def describe_group(group: str, centres: list[dict]) -> str:
    """Plain-language line for a scenario group (dense area or outliers)."""
    if group == "outlier":
        return "picked at random from all residential buildings, anywhere in the area"
    k = area_number(group)
    if k <= len(centres):
        c = centres[k - 1]
        return (
            f"picked near its centre (pin), about {c['weight']:.0%} of buildings; "
            f"inner circle {c['sigma_m']:,.0f} m = typical spread, "
            f"outer circle {2 * c['sigma_m']:,.0f} m"
        )
    return ""


def missing_components(scenario: Scenario) -> bool:
    """A synthetic scenario (it has dense-area centres) whose locations lack labels."""
    has_centres = bool(scenario.meta.parameters.get("centres"))
    return has_centres and all(loc.component is None for loc in scenario.locations)


def sample_buildings(
    buildings: gpd.GeoDataFrame, sample: int | None, seed: int
) -> tuple[gpd.GeoDataFrame, int]:
    """A random sample of at most `sample` buildings (None: all). Returns it and the total."""
    total = len(buildings)
    if sample is None or sample >= total:
        return buildings, total
    return buildings.sample(n=sample, random_state=seed), total

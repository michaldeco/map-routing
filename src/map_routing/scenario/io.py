"""Read and write scenarios: <dir>/scenario.json + <dir>/buildings.csv."""

import json
from pathlib import Path

import pandas as pd

from map_routing.scenario.schema import Location, Scenario, ScenarioMeta

COLUMNS = list(Location.model_fields)


def write_scenario(scenario: Scenario, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for loc in scenario.locations:
        row = loc.model_dump()
        row["allowed_days"] = " ".join(loc.allowed_days)
        rows.append(row)
    pd.DataFrame(rows, columns=COLUMNS).to_csv(directory / "buildings.csv", index=False)
    meta = scenario.meta.model_dump(mode="json")
    meta["locations"] = len(scenario.locations)
    meta["visits_per_week"] = scenario.visits_per_week
    (directory / "scenario.json").write_text(json.dumps(meta, indent=2) + "\n")
    return directory


def read_scenario(directory: Path) -> Scenario:
    """Load and validate; raises pydantic.ValidationError with row details on bad input."""
    meta = json.loads((directory / "scenario.json").read_text())
    meta.pop("locations", None)
    meta.pop("visits_per_week", None)
    # Text columns stay text even when every value looks like a number (e.g. addresses
    # that are only house numbers).
    text = [
        "id",
        "osm_id",
        "address",
        "floors_source",
        "address_source",
        "allowed_days",
        "component",
    ]
    df = pd.read_csv(directory / "buildings.csv", dtype=dict.fromkeys(text, str))
    records = df.astype(object).where(df.notna(), None).to_dict(orient="records")
    return Scenario(meta=ScenarioMeta.model_validate(meta), locations=records)

"""Read and write instances: <dir>/instance.json + <dir>/buildings.csv."""

import json
from pathlib import Path

import pandas as pd

from map_routing.instance.schema import Instance, InstanceMeta, Location

COLUMNS = list(Location.model_fields)


def write_instance(instance: Instance, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for loc in instance.locations:
        row = loc.model_dump()
        row["allowed_days"] = " ".join(loc.allowed_days)
        rows.append(row)
    pd.DataFrame(rows, columns=COLUMNS).to_csv(directory / "buildings.csv", index=False)
    meta = instance.meta.model_dump(mode="json")
    meta["locations"] = len(instance.locations)
    meta["visits_per_week"] = instance.visits_per_week
    (directory / "instance.json").write_text(json.dumps(meta, indent=2) + "\n")
    return directory


def read_instance(directory: Path) -> Instance:
    """Load and validate; raises pydantic.ValidationError with row details on bad input."""
    meta = json.loads((directory / "instance.json").read_text())
    meta.pop("locations", None)
    meta.pop("visits_per_week", None)
    df = pd.read_csv(directory / "buildings.csv", dtype={"id": str, "osm_id": str})
    records = df.astype(object).where(df.notna(), None).to_dict(orient="records")
    return Instance(meta=InstanceMeta.model_validate(meta), locations=records)

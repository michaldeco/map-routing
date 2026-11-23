from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from shapely.geometry import box

from map_routing.scenario.io import read_scenario, write_scenario
from map_routing.scenario.schema import Location, Scenario, ScenarioMeta, outside


def loc(id_="a", **kw):
    data = {"id": id_, "lat": 40.62, "lon": 22.95, "visits_per_week": 2, "duration_min": 30}
    data.update(kw)
    return Location(**data)


def meta():
    return ScenarioMeta(
        name="t",
        area_slug="t",
        source="synthetic",
        created=datetime(2026, 11, 22, tzinfo=UTC),
        seed=1,
    )


def test_round_trip(tmp_path):
    inst = Scenario(
        meta=meta(),
        locations=[
            loc("a", allowed_days="Tue Mon Thu", address="Egnatia 1", floors=6.0),
            loc("b", osm_id="w123", visits_per_week=1, duration_min=45.5),
        ],
    )
    write_scenario(inst, tmp_path)
    back = read_scenario(tmp_path)
    assert back == inst
    assert back.locations[0].allowed_days == ("Mon", "Tue", "Thu")  # canonical order
    assert back.visits_per_week == 3


@pytest.mark.parametrize(
    "kw",
    [
        {"visits_per_week": 0},
        {"visits_per_week": 8},
        {"duration_min": 2},
        {"duration_min": 500},
        {"lat": 95},
        {"allowed_days": "Mon Funday"},
        {"allowed_days": "Mon Mon"},
        {"visits_per_week": 3, "allowed_days": "Mon Tue"},
        {"floors": 0},
    ],
)
def test_invalid_location(kw):
    with pytest.raises(ValidationError):
        loc(**kw)


def test_duplicate_and_empty():
    with pytest.raises(ValidationError, match="duplicate"):
        Scenario(meta=meta(), locations=[loc("a"), loc("a")])
    with pytest.raises(ValidationError, match="no locations"):
        Scenario(meta=meta(), locations=[])


def test_outside_boundary():
    inst = Scenario(meta=meta(), locations=[loc("in"), loc("out", lon=25.0)])
    assert outside(inst, box(22.9, 40.6, 23.0, 40.7)) == ["out"]


def test_csv_errors_are_reported(tmp_path):
    write_scenario(Scenario(meta=meta(), locations=[loc("a")]), tmp_path)
    csv = tmp_path / "buildings.csv"
    csv.write_text(csv.read_text().replace(",2,30.0,", ",9,30.0,"))
    with pytest.raises(ValidationError, match="visits_per_week"):
        read_scenario(tmp_path)

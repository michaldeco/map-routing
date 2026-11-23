from pathlib import Path

from map_routing.settings import DEFAULT_USER_AGENT, load_settings


def test_defaults(monkeypatch):
    monkeypatch.delenv("MAP_ROUTING_DATA_DIR", raising=False)
    monkeypatch.delenv("MAP_ROUTING_USER_AGENT", raising=False)
    s = load_settings()
    assert s.data_dir == Path("data")
    assert s.user_agent == DEFAULT_USER_AGENT
    assert s.area_dir("x") == Path("data/areas/x")


def test_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("MAP_ROUTING_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MAP_ROUTING_USER_AGENT", "custom/1.0")
    s = load_settings()
    assert s.data_dir == tmp_path
    assert s.user_agent == "custom/1.0"

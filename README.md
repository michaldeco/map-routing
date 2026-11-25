# map-routing

Weekly visit scheduling and walking-route optimization for field workers,
on real OpenStreetMap data: which buildings get visited on which day, by
whom, in what order, and how many workers are needed.

Work in progress: M1 (map data and scenarios) is done. See
[docs/PLAN.md](docs/PLAN.md) and [docs/M1_PLAN.md](docs/M1_PLAN.md).

## Usage

Requires Python 3.14 with [uv](https://docs.astral.sh/uv/) and the `osmium`
command-line tool (Fedora: `dnf install osmium-tool`).

```sh
# 1. Define an area (bounding box, GeoJSON polygon or place name) and cut its map data
uv run map-routing area define thessaloniki --bbox 22.85,40.55,23.05,40.70
uv run map-routing area define bratislava-petrzalka --place "Petržalka, Bratislava"
uv run map-routing area fetch thessaloniki

# 2. Extract all buildings, then impute missing values (see quality.json)
uv run map-routing buildings extract thessaloniki
uv run map-routing buildings impute thessaloniki

# 3. Generate a synthetic scenario (the engine's input) and validate it
uv run map-routing scenario generate thessaloniki --size full --seed 1
uv run map-routing scenario validate data/scenarios/thessaloniki-full-s1

# 4. Check the data on a map (served from http://127.0.0.1, opens the browser)
uv run map-routing scenario map data/scenarios/thessaloniki-full-s1
uv run map-routing view data/scenarios/thessaloniki-full-s1/map.html
uv run map-routing buildings map thessaloniki --colour-by floors --residential-only
```

Building maps show a random sample of 5,000 buildings by default (`--sample N`,
or `--all`); colour them by `residential`, `reason`, `floors-source` or `floors`.

## API

`map-routing api` (or `make api`) runs a read-only API on http://127.0.0.1:8000
for the upcoming web app: areas, imputed buildings (sampled, with legend
categories and plain-language explanations) and scenarios, as GeoJSON. Every
endpoint can be tried at http://127.0.0.1:8000/docs. See
[docs/UI_PLAN.md](docs/UI_PLAN.md).

Place names are resolved with Nominatim; set `MAP_ROUTING_USER_AGENT` to
identify yourself if you use it a lot. Data lives in `./data` (override with
`MAP_ROUTING_DATA_DIR`).

## Development

```sh
make install    # dependencies and dev tools
make validate   # lint (ruff), format check (black), tests (pytest)
make format     # fix what ruff can fix, then format with black
make            # list all commands
```

Map data © OpenStreetMap contributors (ODbL).

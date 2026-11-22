# M1 implementation plan: map data and instances

## Context

The route-planning demo (`~/Projects/portfolio/map-routing`, branch `m1-data`)
needs realistic input before any optimization can be built. `docs/PLAN.md`
(commit 3b153b6) defines M1 as four parts with a strict separation:

- **Map data** (M1a area and extract, M1b buildings + imputation): works for
  any OpenStreetMap area; Thessaloniki is only the first example.
- **Instances** (M1c format, M1d synthetic generator): the instance format
  is the engine's only input; the synthetic generator is one source, a user
  import comes later.

The repo has only the skeleton (`pyproject.toml`, empty `src/map_routing/`),
so everything below is new code. Already on disk (gitignored):
`data/raw/greece-latest.osm.pbf` (2026-11-21), `thessaloniki.osm.pbf`,
`thess-buildings.geojsonseq`. `osmium` 1.19.1 is installed.

Decisions from the user: GeoPandas (+ pyarrow, GeoParquet) for geodata;
Typer for the CLI; Nominatim User-Agent generic (`map-routing/0.1`) and
configurable, no personal details by default.

## Architecture and data flow

```
 EXTERNAL SERVICES (HTTP)                  LOCAL TOOLS
 ┌──────────────────────────┐              ┌─────────────────────┐
 │ Nominatim                │              │ osmium CLI          │
 │  place name -> polygon   │              │  extract, tags-     │
 │  (1 req/s, cached)       │              │  filter, export,    │
 └────────────▲─────────────┘              │  fileinfo           │
              │ GET (only for --place)     └──────────▲──────────┘
 ┌────────────┴─────────────┐                         │ subprocess
 │ Geofabrik                │                         │
 │  index-v1.json (weekly)  │                         │
 │  *.osm.pbf + .md5 (once) │                         │
 └────────────▲─────────────┘                         │
              │ GET (cache miss only)                 │
 ═════════════╪═══════════════════════════════════════╪══════════════════
 MAP DATA     │                                       │
              │                                       │
 [1] area define ── bbox | polygon | place ──> area.json
              │
 [1] area fetch ── index -> smallest containing extract -> download ──┐
              │                                                       │
              └──────── data/cache/geofabrik/*.osm.pbf ──> osmium extract
                                                                      │
                                       data/areas/<slug>/area.osm.pbf ┤──> (M2: OSRM
                                                                      │     foot profile)
 [2] buildings extract ── osmium tags-filter + export ────────────────┘
              │
              ├──> buildings_raw.parquet  (every building, raw tags, UTM area)
              └──> context.parquet        (residential land use, address points)
              │
 [3] buildings impute ── rules: residential -> floors -> address
              │          (each fills gaps only, writes *_source)
              ├──> buildings.parquet      (imputed, value sources)
              └──> quality.json           (tagged vs imputed per rule)
 ═════════════╪══════════════════════════════════════════════════════════
 INSTANCES    │ pool of residential buildings
              ▼
 [5] instance generate (synthetic source)      [later] user import (CSV,
      mixture of dense areas + outliers,              geocoding, optional
      nested sizes, seeded demand                     OSM enrichment)
              │                                          │
              └──────────────┬───────────────────────────┘
                             ▼
 [4] instance format + validation (Pydantic) ── the engine's ONLY input
                             │
              data/instances/<slug>-<size>-<seed>/buildings.csv + instance.json
                             │
                             ▼
                 ENGINE (M3–M7: clustering, weekdays, routes, workforce)
```

[n] = step number below. Only steps 1 talk to the network, and only on a
cache miss; everything after `area fetch` runs offline.

## Package layout

```
src/map_routing/
  cli.py                 Typer app: `area`, `buildings`, `instance` command groups
  settings.py            paths (data dir), User-Agent (env MAP_ROUTING_USER_AGENT)
  geo.py                 local UTM CRS from an area's centre; WGS84 <-> UTM helpers
  osmium.py              thin subprocess wrapper around the osmium CLI (extract, tags-filter, export, fileinfo)
  providers/
    geocoding.py         Geocoder protocol + NominatimGeocoder (1 req/s, cached)
  area/
    model.py             Area (name, slug, boundary polygon, source, data date) + area.json IO
    extracts.py          Geofabrik index (cached), pick smallest containing extract, download + md5 check, cut
  buildings/
    extract.py           raw buildings + context layers (residential land use, address points) -> GeoParquet
    impute.py            rule pipeline, value-source columns, quality summary
    rules.py             individual imputation rules (pluggable)
  instance/
    schema.py            Pydantic models: Location, Demand, Workforce, InstanceMeta; validation
    io.py                read/write buildings.csv + instance.json
  synthetic/
    generator.py         mixture sampling (dense areas + outliers), nested sizes, demand
```

M2's other provider interfaces (`TravelTimes`, `RouteGeometry`) are not
part of M1; `providers/` is created now so `Geocoder` sits where they will.

## Data layout

```
data/cache/geofabrik/    index-v1.json, downloaded *.osm.pbf (+ .md5)      gitignored
data/cache/nominatim/    cached geocoding responses                         gitignored
data/areas/<slug>/
  area.json              boundary, source extract, OSM data date, params   committed
  area.osm.pbf           cut extract (input for OSRM in M2)                 gitignored
  buildings_raw.parquet  every building, raw tags                           gitignored
  context.parquet        residential land use polygons, address points      gitignored
  buildings.parquet      imputed buildings with value sources               gitignored
  quality.json           tagged vs imputed counts per field and rule        committed
data/instances/<slug>-<size>-<seed>/
  buildings.csv, instance.json                                               committed (small, ODbL)
```

Move the existing `data/raw/greece-latest.osm.pbf` into `data/cache/geofabrik/`
(path as Geofabrik names it) so it is not downloaded again; delete the rest of
`data/raw/` once M1a reproduces it. `.gitignore`: replace `data/raw/` with
`data/areas/*/*.pbf`, `data/areas/*/*.parquet`; keep `data/cache/`, `data/osrm/`.

## Steps (one commit each on `m1-data`)

### Step 0: dependencies and tooling
- `uv add geopandas pyarrow shapely pyproj scipy pydantic typer`
  (scipy: KD-tree now, needed by OR-Tools work later anyway).
- `uv add --dev pytest ruff black`; `[project.scripts] map-routing = "map_routing.cli:app"`.
- Formatting: black with `line-length = 100` (`[tool.black]` in `pyproject.toml`,
  `target-version` matching the Python version). Ruff is used for linting only,
  with the same `line-length = 100` so the two never disagree (ruff's `E501`
  follows black's width).
- Check all install on Python 3.14; if a wheel is missing, pin `.python-version` to 3.13.

### Step 1 (M1a): area and extract
- `area define <slug> --bbox W,S,E,N | --polygon file.geojson | --place "Thessaloniki, Greece"`
  writes `area.json`. Place names go through `NominatimGeocoder`
  (`polygon_geojson=1`, generic configurable User-Agent, ≥1 s between requests,
  responses cached on disk).
- `area fetch <slug>`: load Geofabrik `index-v1.json` (cached, refreshed if
  older than a week); choose the smallest extract whose geometry contains the
  area polygon; download if missing or md5 mismatch; `osmium extract --polygon`
  (boundary written as GeoJSON) -> `area.osm.pbf`; record the data date from
  `osmium fileinfo` in `area.json`.
- `geo.utm_crs(area)`: EPSG 326xx/327xx from the centroid's longitude and hemisphere.

### Step 2 (M1b, part 1): extract buildings and context
- `buildings extract <slug>`: `osmium tags-filter wr/building` then
  `osmium export --geometry-types=polygon -f geojsonseq` (polygons only; closed
  ways otherwise appear twice) -> GeoPandas -> `buildings_raw.parquet` with
  `osm_id` (e.g. `w123`, `r456`), geometry, centroid, footprint m² (UTM), and
  the tags the rules use (`building`, `building:levels`, `height`, `addr:*`,
  `amenity`, `shop`) plus the full tag dict as JSON.
- Context in the same pass: `landuse=residential` polygons and address points
  (`addr:housenumber` nodes) -> `context.parquet`.

### Step 3 (M1b, part 2): imputation
- `buildings impute <slug> [--config imputation.json]`; defaults in code,
  overrides per area. Each rule fills only missing values and writes a source
  column (`residential_source`, `levels_source`, `address_source`).
- Rules, in order:
  1. Residential: tagged type if residential-like (`apartments`, `residential`,
     `house`, …) -> `osm`; non-residential tags or other building values
     (industrial, school, church, retail, commercial, office, garage, roof, …)
     -> excluded (`osm`); untagged `yes`: footprint between min (default 150 m²)
     and max thresholds and, if enabled, inside `landuse=residential` (spatial
     join) -> `rule:footprint_landuse`.
  2. Floors: `building:levels` -> `osm`; `height`/3 m -> `height`; median of
     tagged buildings within radius R (default 300 m, at least k=5, KD-tree in
     UTM) -> `neighbours`; else default distribution (seeded) -> `default`.
  3. Address: nearest address point within 30 m -> `nearest_point`, else empty.
- `quality.json` + a printed summary table: counts per field and source.
- Rules are small classes with a common interface (`name`, `apply(gdf, context)`),
  so the later classifier is one more rule.

### Step 4 (M1c): instance format
- Pydantic models; `instance validate <path>` command. Checks: unique ids,
  ranges (frequency 1–7, duration 5–240 min, shift > 0), allowed days ⊆ Mon–Sun
  and at least as many as the frequency, points inside the area boundary.
- `buildings.csv` columns: id, osm_id, lat, lon, address, floors,
  footprint_m2, value sources, visits_per_week, duration_min, allowed_days.
  `instance.json`: area slug + data date, source (`synthetic` / later `import`),
  generator parameters and seed, workforce settings (shift length, start
  points optional).

### Step 5 (M1d): synthetic generator
- `instance generate <slug> --size small|medium|full --seed N [--layout mixed|compact] [--load moderate|high]`.
- Pool: imputed residential buildings.
- Mixed layout: choose k centres (default 3) among buildings, weighted by local
  building density and at least D apart (default 1.5 km); component weights
  default 50/30/15 % + 5 % outliers drawn uniformly from the pool; within a
  component, sample with a Gaussian kernel around the centre (radius per
  component). Compact layout: one component.
- Nesting: draw one ordered sample of 1,000 (component per draw by weight,
  without replacement); small/medium/full are prefixes (100/300/1,000).
- Demand (seeded): visits per week from a distribution (moderate: mean ~2;
  high: mean ~5, the 5,000-visits case); duration = 15 + 3 × floors min,
  clipped to 15–90, plus small noise; ~10 % of buildings with a forbidden day.
- Output passes `instance validate` before it is written.

## Tests (pytest)

- Unit, no services: UTM selection (Thessaloniki -> EPSG:32634; a southern
  point -> 327xx); Geofabrik choice from a small fake index; Nominatim adapter
  with a mocked HTTP response (and no request without a cache miss); each
  imputation rule on a small hand-made GeoDataFrame, incl. source columns;
  schema validation failures; generator determinism (same seed -> same CSV),
  nesting, component proportions within tolerance, demand ranges.
- Integration, marked `osmium` (skipped if the binary is missing): a tiny
  hand-written `.osm` fixture with ~10 buildings, one relation, one closed
  way, a landuse polygon and address nodes -> extract + impute end to end.

## Verification

1. `uv run pytest`, `uv run ruff check` and `uv run black --check .`.
2. Thessaloniki end to end:
   `map-routing area define thessaloniki --bbox 22.85,40.55,23.05,40.70`,
   `area fetch`, `buildings extract`, `buildings impute`.
   Check: 113,802 buildings (the count found on 2026-11-21 for the same
   bbox and extract date), apartment/residential counts 6,252 / 3,835,
   and a plausible quality summary.
3. `instance generate thessaloniki --size small|medium|full --seed 1`;
   `instance validate` on each; open the instances in QGIS (or export
   GeoJSON) to eyeball the dense areas and outliers.
4. Second area to prove nothing is Thessaloniki-specific:
   `area define bratislava-test --place "Petržalka, Bratislava"` -> fetch,
   extract, impute, generate small.

## Out of scope for M1

Travel times and OSRM (M2), the classifier rule, user import, report/map.
Commits stay local on `m1-data` until the user asks to push.

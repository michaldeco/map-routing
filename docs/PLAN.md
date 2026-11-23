# Implementation plan

Weekly visit scheduling and walking-route optimization for field workers:
which buildings get cleaned on which day, by whom, in what order, and how
many cleaners are needed. A portfolio demo built for a specific job type
(a Thessaloniki cleaning company: ~1,000 buildings, up to 5,000 recurring
visits per week, real walking times, reoptimization).

The demo proves the optimization and routing parts. It has no web framework,
login, admin or translations; the result is a command-line tool plus a static
HTML report that can be published as a link.

## Stack

- Python 3.14, managed with uv; `src/map_routing` package; pytest, ruff.
- OR-Tools: CP-SAT for weekday assignment, the routing solver for daily routes.
- OpenStreetMap data for any area (Geofabrik extract, cut with osmium);
  Thessaloniki is the first example.
- OSRM with the foot profile, running locally in a container (podman), for
  walking-time matrices.
- Leaflet + OSM tiles in a generated, self-contained HTML report.
- External services behind provider interfaces (travel times, route
  geometry, geocoding, map layer), so providers such as Google can be
  added as adapters without touching the engine.

## Milestones

Each milestone ends with tests and a short note in the write-up.

### M1 Data

Detailed implementation plan: [M1_PLAN.md](M1_PLAN.md).

Works for any area covered by OpenStreetMap; Thessaloniki is the first
example, nothing in the code assumes it. Four steps, each with its own
command, inputs and outputs, so each can be tested and rerun alone.

#### M1a Area and extract

- Area given as a bounding box, a GeoJSON polygon, or a place name (resolved
  to a polygon with Nominatim; respect its usage policy, ~1 request/s).
- Pick the smallest Geofabrik extract containing the area (from Geofabrik's
  index of extracts and their boundaries), download it once, cut the area
  with `osmium extract`. The cut file is also the input for the walking
  router (M2).
- One folder per area, e.g. `data/areas/thessaloniki/`, with `area.json`:
  boundary, source extract, OSM data date, parameters.
- Distances and footprint areas in the local UTM zone, chosen from the area's
  centre (pyproj), so nothing depends on the country.

#### M1b Extract buildings, then impute

- Extract: every building in the area with its raw tags, footprint polygon,
  centroid; no filtering or judgement. (`osmium export
  --geometry-types=polygon`, otherwise closed ways come out twice.)
- Impute: fill missing values with explicit rules and record the source of
  every value (e.g. `levels_source = osm | height | neighbours | default`).
  - Residential or not: tagged type if present; otherwise exclude clearly
    non-residential tags (industrial, school, church, retail, commercial,
    office, garage, roof, …), exclude small footprints (sheds, garages),
    count `landuse=residential` around the building in favour. Thresholds
    are config values with defaults.
  - Floors: `building:levels`; else `height` ÷ ~3 m; else the median of
    tagged buildings nearby (adapts to each city: tall blocks in a centre,
    low houses in a village, within 300 m, then 1,000 m); else the area's
    median floors; else the median of a configured default. Random draws
    instead of medians are opt-in (`floor_fallback: random`) and meant only
    for synthetic data, never for real client data.
  - Address: the nearest address point if any (display only).
- Data-quality summary per run: counts tagged vs imputed, by rule; part of
  the write-up and a quick check for a new area.
- Thessaloniki findings (2026-11-21, Geofabrik extract of that day, bbox
  22.85,40.55,23.05,40.70): 113,802 buildings, 88 % only `building=yes`;
  6,252 `apartments` + 3,835 `residential`. The apartment/residential share
  per ~1.7 km cell ranges from 2 % to 63 % (mapper activity, not real
  density), so selecting by tagged type would bias the areas. Floors tagged
  on ~22 % of apartment/residential buildings, street address on ~64 %.
- Later extension: a classifier trained on the tagged buildings (footprint
  size and shape, land use, neighbourhood features) to predict the type of
  untagged ones. The tagged buildings are not a random sample (they sit
  where mappers were active), so this is a selection-bias problem: evaluate
  with spatially separated test areas, compare with the rules, and consider
  weighting or modelling where tags are present. Rules first; the classifier
  is a separate, swappable imputation rule.

#### M1c Scenario format (the engine's only input)

- Map data (M1a, M1b) and scenarios are separate components. The engine
  reads a scenario and nothing else; it never knows where the scenario
  came from.
- Contract: locations (id, coordinates, optional address and building
  attributes with their value sources), visit demand (visits per week,
  duration, allowed days), workforce settings (shift length, optional
  start points), the area reference (for the travel-time provider).
- Files: `buildings.csv` (or `locations.csv`) + `scenario.json` (parameters,
  area, source, data date, seed if synthetic). A schema with validation
  (Pydantic): ranges, unique ids, points inside the area, consistent
  allowed days vs frequency. Every source passes the same checks.

#### M1d Synthetic scenario generator (one source of scenarios)

- Uses the imputed buildings from M1b as the pool to sample from.
- Spatial layout: real customer bases are uneven, so buildings are sampled
  as a mixture of 2–3 dense areas of different sizes (e.g. 50 / 30 / 15 %)
  plus ~5 % scattered outliers. Number of areas, sizes and outlier share are
  parameters; a single compact area is kept as a simpler comparison case.
- Scenarios: `small` (~100 buildings) for tests and development, `medium`
  (~300), `full` (1,000), nested (small ⊂ medium ⊂ full), same mixture.
- Demand with a fixed seed: visit frequency per week from a configurable
  distribution; cleaning duration from floors and footprint (e.g. 15 min
  + 3 min per floor, kept within 15–90 min); allowed days for a small share
  of buildings. Cleaners: count left open (the engine computes it), shift
  length (e.g. 8 h).
- Load: "up to 5,000 recurring visits" is ambiguous (per week, or visit
  definitions?). Test a moderate load (~2 visits per building per week) and
  the 5,000-visits-per-week case.
- Generated scenarios are not committed (gitignored); regenerate them with `scenario generate`.

#### Later: user import (another source of scenarios)

- CSV with coordinates or addresses, visits per week, duration, allowed
  days; addresses geocoded through the `Geocoder` interface (M2).
- Optional enrichment: match each location to its OSM building and fill
  missing floors or durations with the M1b imputation rules, recording the
  value sources as usual.
- Produces the same scenario format and passes the same validation.

#### Notes for later milestones

- Walking between dense areas is unrealistic (4 km ≈ 50 min), so a cleaner's
  day stays within one area (cap on a single walk, or no crossing between
  areas); isolated buildings need explicit handling and are worth showing in
  the report.
- Open questions for a real client: how cleaners reach the first building
  and move between areas (walking only, public transport, company
  transport); what "5,000 recurring visits" means.
- OSM data is ODbL: credit "© OpenStreetMap contributors" in the report;
  published derived data stays under ODbL.

### M2 Travel times

- Provider interfaces (ports and adapters); the engine only sees arrays:
  - `TravelTimes.matrix(points) -> durations (s), distances (m)`
  - `RouteGeometry.route(points) -> line` (for drawing routes on the map)
  - `Geocoder` (place name → polygon or point; used by M1a)
- Adapters own their batching, rate limits, retries and caching; the
  provider is chosen in config. Cache keyed by provider, profile and point
  set, so results from different providers never mix.
- Implemented now: OSRM (self-hosted in podman, foot profile; raise
  `--max-table-size` for 1,000 × 1,000) and straight-line distance ÷ walking
  speed (tests, no service needed). Nominatim for geocoding.
- Prepared, not implemented: Google (Routes API matrix, Geocoding). Its
  terms require Google results to be shown on a Google map and restrict
  long-term caching (check the current terms before building it), so a
  Google adapter also needs a Google map in the report and a cache policy
  per provider. The report's map layer is therefore pluggable too.
- Other possible adapters, much later:
  - Open source, self-hosted or hosted: Valhalla (good pedestrian costing,
    matrix service), OpenRouteService (hosted free quota or self-hosted),
    GraphHopper (open source; hosted matrix API is paid).
  - Commercial: Mapbox Matrix API, HERE Matrix Routing, TomTom Matrix
    Routing, Azure Maps Route Matrix, Esri ArcGIS.
  - Geocoding: Photon, Pelias (open); Mapbox, HERE (commercial).
  - Map tiles: OSM standard tiles (light use only, per their usage policy),
    MapTiler, Stadia, Thunderforest, or self-hosted Protomaps (one static
    file, fits a static report).
- Check: a few times against common sense (map distance, ~5 km/h walking);
  later, a comparison between providers on the same pairs.

### M3 Clustering

- Group buildings into areas with balanced workload (cleaning + estimated
  walking time), compact in space.
- Start simple (k-means on coordinates, then rebalance); compare with a small
  assignment MILP if balance is poor.

### M4 Weekday assignment (CP-SAT)

- Each building's visits go to weekdays: exact frequency, spacing (2×/week →
  Mon/Thu or Tue/Fri, not consecutive days), allowed days, daily capacity per
  area.
- Objective: even daily workload; later also stability (M7).

### M5 Daily routing (OR-Tools routing)

- Per area and day: routes for the cleaners, with service times, shift
  length, walking times; start/end point (e.g. first building or a depot).
- Time limits and search strategy settings; record solution quality vs time.

### M6 Workforce

- Cleaners needed per day and in total; utilization per cleaner (cleaning vs
  walking vs idle); sensitivity to shift length.

### M7 Reoptimization

- Add or remove buildings, change a frequency; re-solve with a penalty for
  changing existing assignments (day, cleaner).
- Report how many visits moved and the cost difference vs solving from
  scratch.

### M8 Scale test and baselines

- Run the `full` scenario: run time per stage, total walking time, cleaners.
- Baselines: nearest-neighbour routes without clustering; no-spacing weekday
  assignment. Show what each stage of the engine saves.

### M9 Command line and report

- `plan` and `replan` commands; inputs as CSV, outputs as CSV/JSON.
- Static HTML report: map with routes and a day/cleaner selector, workforce
  tables, before/after view for reoptimization, the M8 numbers.
- Short write-up: model, assumptions, results, limits.

### M10 Optional: Google comparison

- Google adapter behind the same interface; capped test (e.g. 50 × 50 pairs
  within the free monthly allowance, check current pricing and terms).
- Compare OSM vs Google walking times; check whether the difference changes
  routes.

## Later, only if needed

PostgreSQL storage with plan versions, a FastAPI API with a background
worker, editing on the map. Possibly a screen recording of a local version
instead of public hosting. See idea #7 in Portfolio Ideas.md for estimates.

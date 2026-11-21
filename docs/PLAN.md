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
- OpenStreetMap data (Geofabrik extract, cut to Thessaloniki with osmium).
- OSRM with the foot profile, running locally in a container (podman), for
  walking-time matrices.
- Leaflet + OSM tiles in a generated, self-contained HTML report.

## Milestones

Each milestone ends with tests and a short note in the write-up.

### M1 Data

- Download the Greece extract, cut a Thessaloniki bounding box (osmium).
- Buildings: residential apartment buildings (`building=apartments`, possibly
  `residential`) as centroids with id, address, levels where tagged.
- Findings (2026-11-21, Geofabrik extract of that day, bbox
  22.85,40.55,23.05,40.70; `osmium export --geometry-types=polygon`, otherwise
  closed ways come out twice): 113,802 buildings, 88 % only `building=yes`;
  6,252 `apartments` + 3,835 `residential`. The apartment/residential share
  per ~1.7 km cell ranges from 2 % to 63 % (mapper activity, not real
  density), so selecting by type would bias the areas. Floors tagged on ~22 %
  of apartment/residential buildings, street address on ~64 %.
- Decision: select by a proxy instead: all buildings with footprint
  ≥ ~150 m², excluding non-residential tags (industrial, school, church,
  retail, commercial, office, garage, roof, …), optionally only inside
  `landuse=residential`. Missing floors are drawn at random; the write-up
  states the rule.
- Synthetic attributes with a fixed seed: visit frequency (1–3 per week),
  cleaning duration (from building size/levels), optional allowed days.
- Cleaners: count left open (the engine computes it), shift length (e.g. 8 h).
- Spatial layout: real customer bases are uneven, so buildings are sampled as
  a mixture: 2–3 dense areas of different sizes (e.g. 50 / 30 / 15 % of
  buildings) plus ~5 % scattered outliers across the city. Number of areas,
  sizes and outlier share are parameters; a single compact area is kept as a
  simpler comparison case.
- Instances: `small` (~100 buildings) for tests and development, `medium`
  (~300), `full` (1,000 buildings), nested (small ⊂ medium ⊂ full) and drawn
  from the same mixture.
- Load: "up to 5,000 recurring visits" is ambiguous (per week, or visit
  definitions?). The frequency distribution is a parameter; test a moderate
  load (~2 visits per building per week) and the 5,000-visits-per-week case.
- Consequences for later milestones: walking between areas is unrealistic
  (4 km ≈ 50 min), so a cleaner's day stays within one area (cap on a single
  walk, or no crossing between areas); isolated buildings need explicit
  handling and are worth showing in the report.
- Open questions for the client: how cleaners reach the first building and
  move between areas (walking only, public transport, company transport);
  what "5,000 recurring visits" means.
- OSM data is ODbL: credit "© OpenStreetMap contributors" in the report;
  published derived data stays under ODbL.

### M2 Travel times

- One interface: `travel_times(points) -> matrix (seconds)`.
- Implementations: OSRM table service (foot profile; raise `--max-table-size`
  for 1,000 × 1,000), and straight-line distance ÷ walking speed for tests.
- Cache matrices on disk keyed by the point set.
- Check: a few OSRM times against common sense (map distance, typical
  walking speed ~5 km/h).

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

- Run the `full` instance: run time per stage, total walking time, cleaners.
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

# UI implementation plan

## Context

M1 produced map data and scenarios; the first maps (folium, static HTML files,
three commands) showed that checking data visually is essential, and that the
later milestones (M3–M7: clusters, weekdays, routes, workforce,
reoptimization; M9: report) all need a map UI. This plan builds that UI once,
properly, so later milestones only add views:

- one command opens a local app in the browser;
- views and options change in the UI without regenerating files;
- functional now, polishable later (no temporary solutions).

## Architecture

```
 browser
 ┌───────────────────────────────────────────────────────────┐
 │ web/  React + TypeScript (Vite)                           │
 │   control panel: area · view · scenario · colour by ·     │
 │                  sample · new sample · residential only    │
 │   map: MapLibre GL JS (WebGL), data-driven styles         │
 │   legend: title, subtitle, explained entries (from API)   │
 │   types generated from the API's OpenAPI description      │
 └──────────────┬──────────────────────────────┬─────────────┘
                │ GET /api/... (JSON, GeoJSON)  │ vector tiles
                ▼                               ▼
 ┌──────────────────────────────┐   ┌───────────────────────────┐
 │ FastAPI (127.0.0.1 only)     │   │ OpenFreeMap (OSM-based,    │
 │   read-only endpoints        │   │ free, no key); later       │
 │   Pydantic response models   │   │ swappable for self-hosted  │
 │   serves built web/ (ui)     │   │ Protomaps                  │
 └──────────────┬───────────────┘   └───────────────────────────┘
                │ reuses
                ▼
   map_routing: Area, buildings.parquet, read_scenario, sampling,
   legends (plain-language explanations, defined once in Python)
```

Decisions:
- **FastAPI**: the engine is Python; Pydantic models become API schemas; the
  OpenAPI description generates the frontend's TypeScript types, so backend
  and frontend cannot drift apart silently.
- **React + TypeScript + Vite**: widespread, component-based, easy to polish
  or hand to a designer later.
- **MapLibre GL JS** (not Leaflet): WebGL handles tens of thousands of points
  and hundreds of routes; colouring is a style rule on the same data, so
  switching views needs no regeneration.
- **Colours live in the frontend**; the API returns categories, counts and
  explanations, in display order. Presentation stays in one place.
- **API models are a separate layer** (`map_routing/api/models.py`): the API
  depends on the core, never the reverse, and the frontend contract changes only
  when these models do. Naming rule, enforced by a test: never reuse a core
  model's name (`Area`, `Scenario`, `Location`, `DenseArea`, ...); resources
  are `...Summary` / `...Detail`, GeoJSON shapes `...Feature` / `...Properties`
  / `...Collection`.
- **Typed core metadata**: synthetic scenarios store `SyntheticInfo` (size,
  layout, load, `DenseArea` list, counts) instead of an untyped dictionary.
- **Points now, footprints later**: buildings are served as centroids; an
  optional footprint geometry can be added when a view needs it.
- **Security**: bound to 127.0.0.1, read-only, every slug and scenario name
  validated (no path traversal), all text rendered as text (no raw HTML).

## Five PRs

Each PR stands alone: reviewable, working and tested. PR 2 was split in three
(setup, buildings, scenarios) because the frontend setup alone is many files.

### PR 1: API (branch `ui-api`, merged)

- `map_routing/legends.py`: plain-language legend content (subtitles,
  explanations, floor bands, scenario group descriptions) moved out of
  `maps.py`, without colours; `maps.py` keeps working on top of it.
- `map_routing/api/`: one router module per resource (`areas.py`,
  `scenarios.py`); `create_app(settings)` only assembles them, puts the data
  store on `app.state` and endpoints receive it as a dependency
  (`dependencies.py`); Pydantic response models in `models.py`.
  Endpoints:
  - `GET /api/health`
  - `GET /api/areas`: slug, name, data date, bounds, whether buildings exist
  - `GET /api/areas/{slug}`: the above plus the boundary (GeoJSON)
  - `GET /api/areas/{slug}/buildings?colour_by=&sample=&seed=&residential_only=&all=`:
    GeoJSON points with building properties and a `category` per feature,
    plus total, shown and the legend
  - `GET /api/scenarios?area=`: scenario summaries
  - `GET /api/scenarios/{name}`: locations as GeoJSON points, dense-area
    centres, legend
- Imputed buildings are cached in memory per area (reloaded when the file
  changes).
- `map-routing api [--port] [--reload]`: runs it with uvicorn on 127.0.0.1;
  `/docs` lets every endpoint be tried in the browser.
- Tests with FastAPI's test client on small generated data.

### PR 2: web setup and area map (branch `ui-web-setup`)

- `web/`: Vite + React + TypeScript, MapLibre GL JS, OpenFreeMap style.
  Node.js 24 and pnpm; exact versions, committed lockfile, packages younger
  than 14 days refused, dependencies' install scripts never run.
- `openapi-typescript` generates `web/src/api/types.ts` from the API
  (`make api-types`); `make validate` fails if it is out of date. The area
  boundary becomes a typed GeoJSON Polygon / MultiPolygon in the API.
- Area selector, area facts, the area boundary on the map.
- `make dev`: API plus Vite dev server (live reload, proxies `/api`).
- `make validate` adds the TypeScript type check, ESLint, Prettier, Vitest
  component tests and a Playwright test in headless Chromium on the
  production build (fake API and basemap, no network): the map loads, with
  MapLibre's worker, and follows the chosen area.

### PR 3: buildings view (branch `ui-web-buildings`)

- Control panel: view, colour by, sample size, new sample, residential only.
- Buildings as coloured points, legend with explanations, popups.

### PR 4: scenario view and one command (branch `ui-web-scenarios`)

- Scenario selector, locations, dense-area centres and spread circles.
- `map-routing ui`: FastAPI serves the API and the built frontend, opens the
  browser; logging configured for the `api` and `ui` commands.

### PR 5: finishing (branch `ui-finish`)

- Playwright tests extended: switching view and colouring updates the legend
  and the points.
- Remove the folium maps (`scenario map`, `buildings map`, `view`), folium
  itself and `maps.py` (and the legend note for scenarios without dense-area
  labels, which current scenarios always have).
- README, PLAN.md and this plan updated.

## Later milestones plug in as views

M3 clusters, M4 weekdays, M5 routes per cleaner and day, M6 workforce, M7
before/after reoptimization: each adds a router module with its endpoints and a view in
the same app.
M9's report becomes a static build of the same frontend with embedded data.

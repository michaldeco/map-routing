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
- **Points now, footprints later**: buildings are served as centroids; an
  optional footprint geometry can be added when a view needs it.
- **Security**: bound to 127.0.0.1, read-only, every slug and scenario name
  validated (no path traversal), all text rendered as text (no raw HTML).

## Three PRs

Each PR stands alone: reviewable, working and tested.

### PR 1: API (branch `ui-api`)

- `map_routing/legends.py`: plain-language legend content (subtitles,
  explanations, floor bands, scenario group descriptions) moved out of
  `maps.py`, without colours; `maps.py` keeps working on top of it.
- `map_routing/api/`: `create_app(settings)`, Pydantic response models.
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

### PR 2: web app (branch `ui-web`)

- `web/`: Vite + React + TypeScript, MapLibre GL JS, OpenFreeMap style.
- `openapi-typescript` generates `web/src/api/types.ts` from the API
  (`make api-types`); a check fails if it is out of date.
- Control panel, map layers (area boundary, buildings or scenario locations,
  dense-area centres and spread circles), legend with explanations, popups.
- `map-routing ui`: FastAPI serves the API and the built frontend, opens the
  browser. `make dev`: Vite dev server (live reload, proxies `/api`) plus the
  API.
- `make validate` adds TypeScript type check, ESLint and Vitest component
  tests; `make web-build`.

### PR 3: finishing (branch `ui-finish`)

- Playwright test in a real browser: the map loads, switching area, view and
  colouring updates the legend and the points.
- Remove the folium maps (`scenario map`, `buildings map`, `view`), folium
  itself and `maps.py`.
- README, PLAN.md and this plan updated.

## Later milestones plug in as views

M3 clusters, M4 weekdays, M5 routes per cleaner and day, M6 workforce, M7
before/after reoptimization: each adds endpoints and a view in the same app.
M9's report becomes a static build of the same frontend with embedded data.

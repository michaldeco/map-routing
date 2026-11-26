import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import {
  apiPaths,
  type AreaDetail,
  type AreaSummary,
  type BuildingCollection,
  DEFAULT_BUILDING_OPTIONS,
} from "./api/client";

// MapLibre needs WebGL, which jsdom lacks; the map has its own test.
vi.mock("./components/MapView", () => ({
  MapView: ({
    boundary,
    buildings,
  }: {
    boundary: AreaDetail["boundary"] | null;
    buildings: BuildingCollection | null;
  }) => (
    <div
      data-testid="map"
      data-boundary={boundary ? JSON.stringify(boundary) : ""}
      data-buildings={buildings ? buildings.features.length : ""}
    />
  ),
}));

function summary(slug: string, name: string, hasBuildings = true): AreaSummary {
  return {
    slug,
    name,
    data_date: "2026-11-21T20:21:02Z",
    bounds: { west: 0, south: 0, east: 1, north: 1 },
    has_buildings: hasBuildings,
  };
}

function detail(area: AreaSummary, x: number): AreaDetail {
  const ring: [number, number][] = [
    [x, 0],
    [x + 1, 0],
    [x + 1, 1],
    [x, 0],
  ];
  return { ...area, boundary: { type: "Polygon", coordinates: [ring] } };
}

/** `n` buildings, all in one legend category named after the colouring. */
function buildings(n: number, colourBy: BuildingCollection["colour_by"]): BuildingCollection {
  return {
    type: "FeatureCollection",
    features: Array.from({ length: n }, (_, i) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [22.5, 0.5] },
      properties: {
        osm_id: `w${i}`,
        building: null,
        residential: true,
        reason: null,
        floors: null,
        floors_source: null,
        footprint_m2: null,
        address: null,
        category: `by ${colourBy}`,
      },
    })),
    colour_by: colourBy,
    total: 10,
    shown: n,
    sampled: n < 10,
    seed: 0,
    legend: {
      title: `Thessaloniki: ${n} of 10 buildings`,
      subtitle: "",
      items: [{ value: `by ${colourBy}`, count: n, description: "" }],
      footer: "",
      note: "",
    },
  };
}

const THESS = summary("thessaloniki", "Thessaloniki");
const PETR = summary("petrzalka", "Petržalka", false);
const THESS_BUILDINGS = apiPaths.buildings("thessaloniki", DEFAULT_BUILDING_OPTIONS);
const THESS_BY_FLOORS = apiPaths.buildings("thessaloniki", {
  ...DEFAULT_BUILDING_OPTIONS,
  colourBy: "floors",
});

/** A fake API: URL -> [status, body]. */
function serve(routes: Record<string, [number, unknown]>) {
  const fetch = vi.fn(async (url: string) => {
    const route = routes[url];
    const [status, body] = route ?? [404, { detail: `no route ${url}` }];
    return new Response(JSON.stringify(body), { status });
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function boundaryOnMap() {
  return screen.getByTestId("map").getAttribute("data-boundary");
}

function buildingsOnMap() {
  return screen.getByTestId("map").getAttribute("data-buildings");
}

let fetch: ReturnType<typeof serve>;

describe("App", () => {
  beforeEach(() => {
    fetch = serve({
      "/api/areas": [200, [THESS, PETR]],
      "/api/areas/thessaloniki": [200, detail(THESS, 22)],
      "/api/areas/petrzalka": [200, detail(PETR, 17)],
      [THESS_BUILDINGS]: [200, buildings(5, "reason")],
      [THESS_BY_FLOORS]: [200, buildings(3, "floors")],
    });
  });

  it("lists the areas and shows the first one on the map", async () => {
    render(<App />);
    const select = await screen.findByRole("combobox", { name: "Area" });
    expect([...select.querySelectorAll("option")].map((o) => o.textContent)).toEqual([
      "Thessaloniki",
      "Petržalka",
    ]);
    await waitFor(() => expect(boundaryOnMap()).toContain("[22,0]"));
    expect(screen.getByText("2026-11-21")).toBeInTheDocument();
  });

  it("shows another area when it is chosen", async () => {
    render(<App />);
    const select = await screen.findByRole("combobox", { name: "Area" });
    await userEvent.selectOptions(select, "petrzalka");
    await waitFor(() => expect(boundaryOnMap()).toContain("[17,0]"));
  });

  it("shows the buildings with their legend, and reloads them when an option changes", async () => {
    render(<App />);
    const legend = await screen.findByRole("region", { name: "Legend" });
    expect(legend).toHaveTextContent("Thessaloniki: 5 of 10 buildings");
    expect(legend).toHaveTextContent("by reason (5)");
    expect(buildingsOnMap()).toBe("5");

    await userEvent.selectOptions(screen.getByLabelText("Colour by"), "floors");
    await waitFor(() => expect(buildingsOnMap()).toBe("3"));
    expect(screen.getByRole("region", { name: "Legend" })).toHaveTextContent("by floors (3)");
  });

  it("offers no buildings view for an area without imputed buildings", async () => {
    render(<App />);
    await screen.findByRole("region", { name: "Legend" });
    await userEvent.selectOptions(screen.getByLabelText("Area"), "petrzalka");
    await waitFor(() => expect(boundaryOnMap()).toContain("[17,0]"));
    expect(screen.queryByLabelText("Colour by")).toBeNull();
    expect(buildingsOnMap()).toBe("");
    const requested = fetch.mock.calls.map(([url]) => url);
    expect(requested.filter((url) => url.startsWith("/api/areas/petrzalka/"))).toEqual([]);
  });

  it("explains how to create an area when there is none", async () => {
    serve({ "/api/areas": [200, []] });
    render(<App />);
    expect(await screen.findByText(/No areas yet/)).toBeInTheDocument();
  });

  it("shows the API's error message", async () => {
    serve({
      "/api/areas": [200, [THESS]],
      "/api/areas/thessaloniki": [500, { detail: "area 'thessaloniki' cannot be read" }],
      [THESS_BUILDINGS]: [200, buildings(5, "reason")],
    });
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Cannot load the area: area 'thessaloniki' cannot be read",
    );
  });

  it("shows the API's error message for buildings", async () => {
    serve({
      "/api/areas": [200, [THESS]],
      "/api/areas/thessaloniki": [200, detail(THESS, 22)],
      [THESS_BUILDINGS]: [500, { detail: "buildings of 'thessaloniki' cannot be read" }],
    });
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Cannot load buildings: buildings of 'thessaloniki' cannot be read",
    );
  });
});

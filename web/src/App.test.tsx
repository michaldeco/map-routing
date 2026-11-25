import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AreaDetail, AreaSummary } from "./api/client";

// MapLibre needs WebGL, which jsdom lacks; the map has its own test.
vi.mock("./components/MapView", () => ({
  MapView: ({ boundary }: { boundary: AreaDetail["boundary"] | null }) => (
    <div data-testid="map" data-boundary={boundary ? JSON.stringify(boundary) : ""} />
  ),
}));

function summary(slug: string, name: string): AreaSummary {
  return {
    slug,
    name,
    data_date: "2026-11-21T20:21:02Z",
    bounds: { west: 0, south: 0, east: 1, north: 1 },
    has_buildings: true,
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

const THESS = summary("thessaloniki", "Thessaloniki");
const PETR = summary("petrzalka", "Petržalka");

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

describe("App", () => {
  beforeEach(() => {
    serve({
      "/api/areas": [200, [THESS, PETR]],
      "/api/areas/thessaloniki": [200, detail(THESS, 22)],
      "/api/areas/petrzalka": [200, detail(PETR, 17)],
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

  it("explains how to create an area when there is none", async () => {
    serve({ "/api/areas": [200, []] });
    render(<App />);
    expect(await screen.findByText(/No areas yet/)).toBeInTheDocument();
  });

  it("shows the API's error message", async () => {
    serve({
      "/api/areas": [200, [THESS]],
      "/api/areas/thessaloniki": [500, { detail: "area 'thessaloniki' cannot be read" }],
    });
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Cannot load the area: area 'thessaloniki' cannot be read",
    );
  });
});

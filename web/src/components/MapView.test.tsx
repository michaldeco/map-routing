import { act, render } from "@testing-library/react";
import { setWorkerUrl } from "maplibre-gl";
import { describe, expect, it, vi } from "vitest";

import type { Boundary, BuildingCollection } from "../api/client";
import { BUILDINGS_LAYER, BUILDINGS_SOURCE, PALETTE } from "../map/buildings";
import { BOUNDARY_SOURCE } from "../map/style";
import { MapView } from "./MapView";

type Handler = (event?: unknown) => void;

// A stand-in for MapLibre's Map (which needs WebGL): records what the component does.
const maps: FakeMap[] = [];

class FakeMap {
  // "event" or "event:layer" -> handlers; `once` handlers are dropped after one call.
  handlers: Record<string, { handler: Handler; once: boolean }[]> = {};
  sources: Record<string, { setData: ReturnType<typeof vi.fn> }> = {};
  canvas = { style: { cursor: "" } };
  fitBounds = vi.fn();
  remove = vi.fn();
  addControl = vi.fn();
  addLayer = vi.fn();
  setPaintProperty = vi.fn();

  constructor() {
    maps.push(this);
  }

  /** `on(event, handler)` or `on(event, layer, handler)`, as in MapLibre. */
  on(event: string, layerOrHandler: string | Handler, handler?: Handler) {
    this.add(event, layerOrHandler, handler, false);
  }

  once(event: string, layerOrHandler: string | Handler, handler?: Handler) {
    this.add(event, layerOrHandler, handler, true);
  }

  off(event: string, handler: Handler) {
    this.handlers[event] = (this.handlers[event] ?? []).filter((h) => h.handler !== handler);
  }

  /** Simulates MapLibre firing an event. */
  fire(key: string, event?: unknown) {
    const handlers = this.handlers[key] ?? [];
    this.handlers[key] = handlers.filter((h) => !h.once);
    act(() => handlers.forEach((h) => h.handler(event)));
  }

  addSource(id: string) {
    this.sources[id] = { setData: vi.fn() };
  }

  getSource(id: string) {
    return this.sources[id];
  }

  getCanvas() {
    return this.canvas;
  }

  private add(event: string, a: string | Handler, b: Handler | undefined, once: boolean) {
    const key = typeof a === "string" ? `${event}:${a}` : event;
    const handler = typeof a === "string" ? b! : a;
    (this.handlers[key] ??= []).push({ handler, once });
  }
}

// Popups record their content and whether they are open; `popups` lists every popup
// created, in order.
const popups: FakePopup[] = [];

class FakePopup {
  text = "";
  content: HTMLElement | null = null;
  isOpen = false;
  closeHandlers: (() => void)[] = [];

  constructor() {
    popups.push(this);
  }

  setLngLat = vi.fn(() => this);
  setText(text: string) {
    this.text = text;
    return this;
  }
  setDOMContent(content: HTMLElement) {
    this.content = content;
    return this;
  }
  addTo() {
    this.isOpen = true;
    return this;
  }
  on(_event: "close", handler: () => void) {
    this.closeHandlers.push(handler);
  }
  /** Like MapLibre: removing an open popup fires "close". */
  remove() {
    if (!this.isOpen) return;
    this.isOpen = false;
    this.closeHandlers.forEach((handler) => handler());
  }
}

vi.mock("maplibre-gl", () => ({
  Map: vi.fn(function (this: unknown) {
    return new FakeMap();
  }),
  Popup: vi.fn(function (this: unknown) {
    return new FakePopup();
  }),
  NavigationControl: vi.fn(),
  ScaleControl: vi.fn(),
  setWorkerUrl: vi.fn(),
}));

const BOUNDARY: Boundary = {
  type: "Polygon",
  coordinates: [
    [
      [0, 0],
      [1, 0],
      [1, 1],
      [0, 0],
    ],
  ],
};
const BOUNDS = { west: 0, south: 0, east: 1, north: 1 };

function buildingsColouredBy(...categories: string[]): BuildingCollection {
  return {
    type: "FeatureCollection",
    features: categories.map((category, i) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [0.5, i / 10] },
      properties: {
        osm_id: `w${i}`,
        building: "apartments",
        residential: true,
        reason: "building=apartments",
        floors: 5,
        floors_source: "osm",
        footprint_m2: 300,
        address: "Main street 1",
        category,
      },
    })),
    colour_by: "reason",
    total: categories.length,
    shown: categories.length,
    sampled: false,
    seed: 0,
    legend: {
      title: "Testville",
      subtitle: "",
      items: [...new Set(categories)].map((value) => ({
        value,
        count: 1,
        description: `means ${value}`,
      })),
      footer: "",
      note: "",
    },
  };
}

function loadedMap() {
  const map = maps.at(-1)!;
  map.fire("load");
  return map;
}

// MapView sets the worker URL once, when imported; Vitest clears call records
// before each test, so they are copied here.
const workerUrlCalls = [...vi.mocked(setWorkerUrl).mock.calls];

describe("MapView", () => {
  it("points MapLibre to its worker file (otherwise no map loads under Vite)", () => {
    expect(workerUrlCalls).toEqual([[expect.stringContaining("maplibre-gl-worker")]]);
  });

  it("draws the boundary and zooms to the area once the map has loaded", () => {
    const { getByTestId } = render(
      <MapView boundary={BOUNDARY} bounds={BOUNDS} buildings={null} />,
    );
    const map = loadedMap();
    expect(getByTestId("map")).toHaveAttribute("data-ready", "false");
    map.fire("idle");
    expect(getByTestId("map")).toHaveAttribute("data-ready", "true");
    expect(map.sources[BOUNDARY_SOURCE]!.setData).toHaveBeenLastCalledWith({
      type: "Feature",
      properties: {},
      geometry: BOUNDARY,
    });
    expect(map.fitBounds).toHaveBeenCalledWith(
      [
        [0, 0],
        [1, 1],
      ],
      expect.anything(),
    );
  });

  it("updates the same map when the area changes, and removes it on unmount", () => {
    const { rerender, unmount } = render(
      <MapView boundary={null} bounds={null} buildings={null} />,
    );
    const map = loadedMap();
    const created = maps.length;
    rerender(<MapView boundary={BOUNDARY} bounds={BOUNDS} buildings={null} />);
    expect(maps.length).toBe(created); // not re-created
    expect(map.sources[BOUNDARY_SOURCE]!.setData).toHaveBeenLastCalledWith(
      expect.objectContaining({ geometry: BOUNDARY }),
    );
    unmount();
    expect(map.remove).toHaveBeenCalled();
  });

  it("draws the buildings in their legend colours, without moving the map", () => {
    const { getByTestId, rerender } = render(
      <MapView boundary={BOUNDARY} bounds={BOUNDS} buildings={null} />,
    );
    const map = loadedMap();
    map.fitBounds.mockClear();
    const buildings = buildingsColouredBy("a", "b", "a");
    rerender(<MapView boundary={BOUNDARY} bounds={BOUNDS} buildings={buildings} />);
    expect(map.sources[BUILDINGS_SOURCE]!.setData).toHaveBeenLastCalledWith(buildings);
    expect(map.setPaintProperty).toHaveBeenLastCalledWith(BUILDINGS_LAYER, "circle-color", [
      "match",
      ["get", "category"],
      "a",
      PALETTE[0],
      "b",
      PALETTE[1],
      expect.any(String),
    ]);
    expect(map.fitBounds).not.toHaveBeenCalled();
    expect(getByTestId("map")).toHaveAttribute("data-buildings", "");
    map.fire("idle");
    expect(getByTestId("map")).toHaveAttribute("data-buildings", "3");
  });

  it("explains a building on hover and shows its details on click", () => {
    const buildings = buildingsColouredBy("a");
    render(<MapView boundary={BOUNDARY} bounds={BOUNDS} buildings={buildings} />);
    const map = loadedMap();
    const event = { lngLat: [0.5, 0], features: [buildings.features[0]] };

    map.fire(`mousemove:${BUILDINGS_LAYER}`, event);
    expect(popups.at(-1)!.text).toBe("a: means a");
    expect(map.canvas.style.cursor).toBe("pointer");

    map.fire(`click:${BUILDINGS_LAYER}`, event);
    expect(popups.at(-1)!.content).toHaveTextContent("Floors5 (known)");
    expect(popups.at(-1)!.content).toHaveTextContent("AddressMain street 1");
  });

  it("shows no tooltip over an open details popup", () => {
    const buildings = buildingsColouredBy("a");
    render(<MapView boundary={BOUNDARY} bounds={BOUNDS} buildings={buildings} />);
    const map = loadedMap();
    const tooltip = popups.at(-1)!;
    const event = { lngLat: [0.5, 0], features: [buildings.features[0]] };

    map.fire(`click:${BUILDINGS_LAYER}`, event);
    const details = popups.at(-1)!;
    map.fire(`mousemove:${BUILDINGS_LAYER}`, event);
    expect(details.isOpen).toBe(true);
    expect(tooltip.isOpen).toBe(false);

    details.remove(); // the user closes it
    map.fire(`mousemove:${BUILDINGS_LAYER}`, event);
    expect(tooltip.isOpen).toBe(true);
  });

  it("closes the popups when the buildings change", () => {
    const buildings = buildingsColouredBy("a");
    const { rerender } = render(
      <MapView boundary={BOUNDARY} bounds={BOUNDS} buildings={buildings} />,
    );
    const map = loadedMap();
    map.fire(`click:${BUILDINGS_LAYER}`, {
      lngLat: [0.5, 0],
      features: [buildings.features[0]],
    });
    const details = popups.at(-1)!;
    expect(details.isOpen).toBe(true);

    rerender(<MapView boundary={BOUNDARY} bounds={BOUNDS} buildings={null} />);
    expect(details.isOpen).toBe(false);
  });
});

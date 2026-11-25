import { act, render } from "@testing-library/react";
import { setWorkerUrl } from "maplibre-gl";
import { describe, expect, it, vi } from "vitest";

import type { Boundary } from "../api/client";
import { BOUNDARY_SOURCE } from "../map/style";
import { MapView } from "./MapView";

// A stand-in for MapLibre's Map (which needs WebGL): records what the component does.
const maps: FakeMap[] = [];

class FakeMap {
  handlers: Record<string, () => void> = {};
  sources: Record<string, { setData: ReturnType<typeof vi.fn> }> = {};
  fitBounds = vi.fn();
  remove = vi.fn();
  addControl = vi.fn();
  addLayer = vi.fn();

  constructor() {
    maps.push(this);
  }

  on(event: string, handler: () => void) {
    this.handlers[event] = handler;
  }

  once(event: string, handler: () => void) {
    this.handlers[event] = handler;
  }

  off() {}

  addSource(id: string) {
    this.sources[id] = { setData: vi.fn() };
  }

  getSource(id: string) {
    return this.sources[id];
  }
}

vi.mock("maplibre-gl", () => ({
  Map: vi.fn(function (this: unknown) {
    return new FakeMap();
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

function loadedMap() {
  const map = maps.at(-1)!;
  act(() => map.handlers.load!());
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
    const { getByTestId } = render(<MapView boundary={BOUNDARY} bounds={BOUNDS} />);
    const map = loadedMap();
    expect(getByTestId("map")).toHaveAttribute("data-ready", "false");
    act(() => map.handlers.idle!());
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
    const { rerender, unmount } = render(<MapView boundary={null} bounds={null} />);
    const map = loadedMap();
    const created = maps.length;
    rerender(<MapView boundary={BOUNDARY} bounds={BOUNDS} />);
    expect(maps.length).toBe(created); // not re-created
    expect(map.sources[BOUNDARY_SOURCE]!.setData).toHaveBeenLastCalledWith(
      expect.objectContaining({ geometry: BOUNDARY }),
    );
    unmount();
    expect(map.remove).toHaveBeenCalled();
  });
});

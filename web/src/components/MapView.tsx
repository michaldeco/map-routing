import {
  type GeoJSONSource,
  Map as MapLibreMap,
  type MapLayerMouseEvent,
  NavigationControl,
  Popup,
  ScaleControl,
  setWorkerUrl,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { useEffect, useRef, useState } from "react";

import type { Boundary, Bounds, BuildingCollection, BuildingProperties } from "../api/client";
import {
  addBuildingLayers,
  buildingDetails,
  buildingSummary,
  BUILDINGS_LAYER,
  BUILDINGS_SOURCE,
  categoryColours,
  colourExpression,
} from "../map/buildings";
import { addBoundaryLayers, BASEMAP_STYLE, BOUNDARY_SOURCE } from "../map/style";

interface Props {
  boundary: Boundary | null;
  bounds: Bounds | null;
  buildings: BuildingCollection | null;
}

const FIT_PADDING_PX = 40;
const EMPTY = { type: "FeatureCollection", features: [] } as const;

// MapLibre decodes tiles in a web worker loaded from a separate file, which it looks
// for next to its own module. Vite bundles MapLibre elsewhere (in development under
// .vite/deps/), so that lookup fails and no map loads. The `?url` import makes Vite
// serve the worker file in development and copy it into the production build.
setWorkerUrl(workerUrl);

/**
 * The map. MapLibre is imperative, so React only creates it once and then pushes
 * data changes into its sources; the map itself is never re-created.
 */
export function MapView({ boundary, bounds, buildings }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  // Legend explanations by category, for the hover text. A ref, not state: the mouse
  // handlers are registered once and read the current value when they run.
  const explanations = useRef<Record<string, string>>({});
  const [ready, setReady] = useState(false); // style loaded, sources exist
  const [drawn, setDrawn] = useState<Boundary | null>(null); // boundary fully rendered
  const [drawnBuildings, setDrawnBuildings] = useState<BuildingCollection | null>(null);

  // An effect is code React runs after it has updated the page; the list at its end
  // says when to run it again (here `[]`: never, only once after the first render).
  // The function it returns runs when the component disappears.
  // This one creates the map in the <div> below, which exists only after rendering.
  useEffect(() => {
    if (!container.current) return;
    const map = new MapLibreMap({
      container: container.current,
      style: BASEMAP_STYLE,
      center: [0, 20],
      zoom: 1,
    });
    map.addControl(new NavigationControl(), "top-right");
    map.addControl(new ScaleControl(), "bottom-left");
    map.on("load", () => {
      addBoundaryLayers(map);
      addBuildingLayers(map); // added last, so drawn on top of the boundary
      setReady(true);
    });

    // Hover: a small tooltip that follows the mouse. Click: a popup with details.
    const tooltip = new Popup({ closeButton: false, closeOnClick: false, offset: 8 });
    map.on("mousemove", BUILDINGS_LAYER, (e: MapLayerMouseEvent) => {
      const category = String(e.features?.[0]?.properties.category ?? "");
      map.getCanvas().style.cursor = "pointer";
      tooltip
        .setLngLat(e.lngLat)
        .setText(buildingSummary(category, explanations.current[category]))
        .addTo(map);
    });
    map.on("mouseleave", BUILDINGS_LAYER, () => {
      map.getCanvas().style.cursor = "";
      tooltip.remove();
    });
    map.on("click", BUILDINGS_LAYER, (e: MapLayerMouseEvent) => {
      const feature = e.features?.[0];
      if (!feature) return;
      tooltip.remove();
      new Popup({ maxWidth: "320px" })
        .setLngLat(e.lngLat)
        .setDOMContent(buildingDetails(feature.properties as Partial<BuildingProperties>))
        .addTo(map);
    });

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Runs after every render in which `ready`, `boundary` or `bounds` changed: pushes the
  // current area into the existing map.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    map
      .getSource<GeoJSONSource>(BOUNDARY_SOURCE)
      ?.setData(boundary ? { type: "Feature", properties: {}, geometry: boundary } : EMPTY);
    if (bounds) {
      map.fitBounds(
        [
          [bounds.west, bounds.south],
          [bounds.east, bounds.north],
        ],
        { padding: FIT_PADDING_PX, duration: 0 },
      );
    }
    // "idle": everything requested is loaded and rendered. GeoJSON is processed in
    // MapLibre's worker, so this also proves the worker runs.
    const onIdle = () => setDrawn(boundary);
    map.once("idle", onIdle);
    return () => {
      map.off("idle", onIdle);
    };
  }, [ready, boundary, bounds]);

  // Pushes the buildings and their colours into the map. Does not move the map: the
  // view stays where the user left it when only the colouring or sample changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const colours = buildings ? categoryColours(buildings.colour_by, buildings.legend.items) : {};
    explanations.current = Object.fromEntries(
      (buildings?.legend.items ?? []).map((item) => [item.value, item.description]),
    );
    map.getSource<GeoJSONSource>(BUILDINGS_SOURCE)?.setData(buildings ?? EMPTY);
    map.setPaintProperty(BUILDINGS_LAYER, "circle-color", colourExpression(colours));
    const onIdle = () => setDrawnBuildings(buildings);
    map.once("idle", onIdle);
    return () => {
      map.off("idle", onIdle);
    };
  }, [ready, buildings]);

  // `data-ready`: the current area is drawn on the map; `data-buildings`: how many
  // buildings are drawn (empty while they are loading). Both are used by browser tests.
  return (
    <div
      ref={container}
      className="map"
      data-testid="map"
      data-ready={boundary !== null && drawn === boundary ? "true" : "false"}
      data-buildings={
        buildings !== null && drawnBuildings === buildings ? buildings.features.length : ""
      }
    />
  );
}

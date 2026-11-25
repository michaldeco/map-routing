import {
  type GeoJSONSource,
  Map as MapLibreMap,
  NavigationControl,
  ScaleControl,
  setWorkerUrl,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { useEffect, useRef, useState } from "react";

import type { Boundary, Bounds } from "../api/client";
import { addBoundaryLayers, BASEMAP_STYLE, BOUNDARY_SOURCE } from "../map/style";

interface Props {
  boundary: Boundary | null;
  bounds: Bounds | null;
}

const FIT_PADDING_PX = 40;

// MapLibre decodes tiles in a web worker loaded from a separate file, which it looks
// for next to its own module. Vite bundles MapLibre elsewhere (in development under
// .vite/deps/), so that lookup fails and no map loads. The `?url` import makes Vite
// serve the worker file in development and copy it into the production build.
setWorkerUrl(workerUrl);

/**
 * The map. MapLibre is imperative, so React only creates it once and then pushes
 * data changes into its sources; the map itself is never re-created.
 */
export function MapView({ boundary, bounds }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [ready, setReady] = useState(false); // style loaded, sources exist
  const [drawn, setDrawn] = useState<Boundary | null>(null); // boundary fully rendered

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
      setReady(true);
    });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    map
      .getSource<GeoJSONSource>(BOUNDARY_SOURCE)
      ?.setData(
        boundary
          ? { type: "Feature", properties: {}, geometry: boundary }
          : { type: "FeatureCollection", features: [] },
      );
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

  // `data-ready`: the current area is drawn on the map (used by browser tests).
  return (
    <div
      ref={container}
      className="map"
      data-testid="map"
      data-ready={boundary !== null && drawn === boundary ? "true" : "false"}
    />
  );
}

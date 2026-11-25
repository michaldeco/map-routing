/**
 * Map appearance: basemap and layer styles. Colours live here, in the frontend only;
 * the API sends categories and explanations, never colours.
 */
import type { Map as MapLibreMap } from "maplibre-gl";

/** OpenFreeMap: free OpenStreetMap vector tiles, no API key. Positron is light and
 * quiet, so data drawn on top stands out. */
export const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";

export const BOUNDARY_SOURCE = "area-boundary";

const BOUNDARY_COLOUR = "#1f5fbf";

/** Area boundary: a light fill and a solid outline. */
export function addBoundaryLayers(map: MapLibreMap): void {
  map.addSource(BOUNDARY_SOURCE, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  map.addLayer({
    id: "area-boundary-fill",
    type: "fill",
    source: BOUNDARY_SOURCE,
    paint: { "fill-color": BOUNDARY_COLOUR, "fill-opacity": 0.05 },
  });
  map.addLayer({
    id: "area-boundary-line",
    type: "line",
    source: BOUNDARY_SOURCE,
    paint: { "line-color": BOUNDARY_COLOUR, "line-width": 2 },
  });
}

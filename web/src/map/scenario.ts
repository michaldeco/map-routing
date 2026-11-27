/**
 * A scenario's locations on the map: one dot per location, coloured by how the
 * generator picked it (its dense area, or an outlier) and sized by visits per week.
 */
import type { Map as MapLibreMap } from "maplibre-gl";

import type { LegendItem, LocationProperties } from "../api/client";
import { detailsList, floorsText, OTHER_COLOUR, osmLink, PALETTE } from "./buildings";

export const SCENARIO_SOURCE = "scenario";
export const SCENARIO_LAYER = "scenario-locations";

/** Dot radius in pixels for the fewest and the most visits per week (1 to 7); sizes
 * in between are interpolated, so busier locations stand out. */
const RADIUS_BY_VISITS = [1, 3, 7, 8] as const;

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
/** Hue step in degrees for colours beyond the palette: each step lands the new hue
 * far from all the earlier ones. */
const GOLDEN_ANGLE = 137.5;

/** Colour of each legend group: palette colours in legend order (area1, area2, ...),
 * and grey for outliers, which belong to no dense area. */
export function groupColours(items: LegendItem[]): Record<string, string> {
  const colours: Record<string, string> = {};
  let next = 0;
  for (const { value } of items) {
    colours[value] = value === "outlier" ? OTHER_COLOUR : groupColour(next++);
  }
  return colours;
}

/** The colour of the i-th dense area (counting from 0): the palette's hand-picked
 * colours first; beyond them (a rare case), computed hues, so that no two dense areas
 * share a colour. */
function groupColour(i: number): string {
  return PALETTE[i] ?? `hsl(${(GOLDEN_ANGLE * i) % 360}, 65%, 45%)`;
}

/** Locations: dots like the buildings', sized by visits per week. */
export function addScenarioLayers(map: MapLibreMap): void {
  map.addSource(SCENARIO_SOURCE, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  const [fewVisits, smallRadius, manyVisits, largeRadius] = RADIUS_BY_VISITS;
  map.addLayer({
    id: SCENARIO_LAYER,
    type: "circle",
    source: SCENARIO_SOURCE,
    paint: {
      "circle-radius": [
        "interpolate",
        ["linear"],
        ["get", "visits_per_week"],
        fewVisits,
        smallRadius,
        manyVisits,
        largeRadius,
      ],
      "circle-color": OTHER_COLOUR,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 0.5,
      "circle-opacity": 0.85,
    },
  });
}

/**
 * Click popup: one location's visits and building. Like the building popup, every
 * field may be missing; in addition MapLibre hands over list properties
 * (`allowed_days`) as JSON text, not as a list.
 */
export function locationDetails(p: Partial<LocationProperties>): HTMLElement {
  return detailsList([
    ["Location", p.id],
    ["OpenStreetMap", p.osm_id ? osmLink(p.osm_id) : null],
    ["Visits per week", p.visits_per_week?.toString()],
    ["Visit length", p.duration_min == null ? null : `${Math.round(p.duration_min)} min`],
    ["Allowed days", daysText(p.allowed_days)],
    ["Floors", floorsText(p.floors, p.floors_source)],
    ["Address", p.address],
  ]);
}

/** "any day" when no day is excluded, otherwise the days, e.g. "Mon, Tue, Wed". */
function daysText(days: string[] | string | undefined): string | null {
  if (days === undefined) return null;
  const list: string[] = typeof days === "string" ? (JSON.parse(days) as string[]) : days;
  if (WEEKDAYS.every((day) => list.includes(day))) return "any day";
  return list.join(", ");
}

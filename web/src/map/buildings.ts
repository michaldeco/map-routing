/**
 * Buildings on the map: colours per legend category, the point layer and the text of
 * the hover tooltip and click popup. The API decides the categories (and explains
 * them); the colours are decided here.
 */
import type { ExpressionSpecification, Map as MapLibreMap } from "maplibre-gl";

import type { BuildingProperties, ColourBy, LegendItem } from "../api/client";

export const BUILDINGS_SOURCE = "buildings";
export const BUILDINGS_LAYER = "buildings-points";

/** Distinct colours for unordered categories: the colour-blind friendly "Tableau 10"
 * palette, with its last colour (a light grey, #bab0ac) replaced by olive (from
 * matplotlib's "tab10"): grey is reserved for "other". The API keeps ten categories
 * and groups the rest into "other", so ten colours are enough. */
export const PALETTE = [
  "#4e79a7",
  "#f28e2b",
  "#59a14f",
  "#e15759",
  "#76b7b2",
  "#edc948",
  "#b07aa1",
  "#ff9da7",
  "#9c755f",
  "#bcbd22",
];
/** "other" (grouped rare values): a neutral grey, so it does not look like a category. */
export const OTHER_COLOUR = "#7f7f7f";
/** Floor bands are ordered, so they get a light-to-dark scale instead of distinct
 * colours: darker means taller. */
export const FLOOR_COLOURS: Record<string, string> = {
  "1–2 floors": "#fdd49e",
  "3–4 floors": "#fc8d59",
  "5–6 floors": "#e34a33",
  "7–9 floors": "#b30000",
  "10+ floors": "#4a0000",
  unknown: "#c7c7c7", // its own light grey, distinct from OTHER_COLOUR
};

const POINT_RADIUS_PX = 4;

/** Colour of each legend category. Unordered categories take palette colours in legend
 * order (most frequent first), so the largest groups get the clearest colours. */
export function categoryColours(colourBy: ColourBy, items: LegendItem[]): Record<string, string> {
  const colours: Record<string, string> = {};
  let next = 0;
  for (const { value } of items) {
    if (colourBy === "floors") colours[value] = FLOOR_COLOURS[value] ?? OTHER_COLOUR;
    else if (value === "other") colours[value] = OTHER_COLOUR;
    else colours[value] = PALETTE[next++ % PALETTE.length]!;
  }
  return colours;
}

/** A MapLibre expression that picks a point's colour from one of its properties
 * (buildings: `category`, scenario locations: `group`), i.e.
 * `match(category, value1, colour1, value2, colour2, ..., fallback)`. */
export function colourExpression(
  colours: Record<string, string>,
  property = "category",
): ExpressionSpecification | string {
  const pairs = Object.entries(colours).flat();
  if (pairs.length === 0) return OTHER_COLOUR; // `match` needs at least one pair
  // MapLibre's type lists the pairs one by one; a pair list of unknown length cannot
  // be checked against it, hence the cast (the pairs check above keeps it valid).
  return ["match", ["get", property], ...pairs, OTHER_COLOUR] as unknown as ExpressionSpecification;
}

/** Buildings: small dots with a thin white outline, so overlapping dots stay apart. */
export function addBuildingLayers(map: MapLibreMap): void {
  map.addSource(BUILDINGS_SOURCE, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  map.addLayer({
    id: BUILDINGS_LAYER,
    type: "circle",
    source: BUILDINGS_SOURCE,
    paint: {
      "circle-radius": POINT_RADIUS_PX,
      "circle-color": OTHER_COLOUR,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 0.5,
      "circle-opacity": 0.85,
    },
  });
}

/** Hover text: the building's category and what it means. */
export function buildingSummary(category: string, explanation: string | undefined): string {
  return explanation ? `${category}: ${explanation}` : category;
}

/**
 * Click popup: what is known about one building. Built from DOM elements rather than
 * an HTML string, so text from OpenStreetMap (addresses, tags) can never be read as
 * HTML.
 *
 * MapLibre hands over a clicked feature's properties without the empty ones, so every
 * field may be missing here even where the API type says `null`.
 */
export function buildingDetails(p: Partial<BuildingProperties>): HTMLElement {
  const rows: [string, string | Node | null | undefined][] = [
    ["OpenStreetMap", p.osm_id ? osmLink(p.osm_id) : null],
    ["Type", p.building],
    ["Residential", p.residential === undefined ? null : p.residential ? "yes" : "no"],
    ["Why", p.reason],
    ["Floors", floorsText(p.floors, p.floors_source)],
    ["Ground area", p.footprint_m2 == null ? null : `${Math.round(p.footprint_m2)} m²`],
    ["Address", p.address],
  ];
  return detailsList(rows);
}

/** A popup's rows as a `<dl>` list of label and value; rows without a value are left
 * out. Shared by the building and scenario location popups. */
export function detailsList(rows: [string, string | Node | null | undefined][]): HTMLElement {
  const list = document.createElement("dl");
  list.className = "details";
  for (const [label, value] of rows) {
    if (value == null || value === "") continue;
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.append(value);
    list.append(term, description);
  }
  return list;
}

/** "5 (known)" for floors tagged in OpenStreetMap, "5 (estimated)" for imputed ones;
 * the "Source of floors" colouring explains each estimate. */
export function floorsText(floors: number | null | undefined, source: string | null | undefined) {
  if (floors == null) return null;
  return `${floors} (${source === "osm" ? "known" : "estimated"})`;
}

/** OSM ids are "w123" (way), "r456" (relation) or "n789" (node). */
const OSM_TYPES: Record<string, string> = { n: "node", w: "way", r: "relation" };

export function osmLink(osmId: string): Node {
  const type = OSM_TYPES[osmId[0] ?? ""];
  if (!type) return document.createTextNode(osmId);
  const link = document.createElement("a");
  link.href = `https://www.openstreetmap.org/${type}/${osmId.slice(1)}`;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = osmId;
  return link;
}

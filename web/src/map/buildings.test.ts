import { describe, expect, it } from "vitest";

import type { LegendItem } from "../api/client";
import {
  buildingDetails,
  buildingSummary,
  categoryColours,
  colourExpression,
  FLOOR_COLOURS,
  OTHER_COLOUR,
  PALETTE,
} from "./buildings";

function items(...values: string[]): LegendItem[] {
  return values.map((value) => ({ value, count: 1, description: "" }));
}

describe("categoryColours", () => {
  it("gives palette colours in legend order and grey to 'other'", () => {
    expect(categoryColours("reason", items("b", "a", "other"))).toEqual({
      b: PALETTE[0],
      a: PALETTE[1],
      other: OTHER_COLOUR,
    });
  });

  it("never gives a category a grey, which would look like 'other'", () => {
    // Grey: red, green and blue nearly equal.
    const isGrey = (hex: string) => {
      const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) as number[];
      return Math.max(r!, g!, b!) - Math.min(r!, g!, b!) < 24;
    };
    expect(isGrey(OTHER_COLOUR)).toBe(true);
    expect(PALETTE.filter(isGrey)).toEqual([]);
  });

  it("gives floor bands their fixed light-to-dark colours", () => {
    expect(categoryColours("floors", items("10+ floors", "1–2 floors", "unknown"))).toEqual({
      "10+ floors": FLOOR_COLOURS["10+ floors"],
      "1–2 floors": FLOOR_COLOURS["1–2 floors"],
      unknown: FLOOR_COLOURS.unknown,
    });
  });
});

describe("colourExpression", () => {
  it("matches each category to its colour, others grey", () => {
    expect(colourExpression({ a: "#111111" })).toEqual([
      "match",
      ["get", "category"],
      "a",
      "#111111",
      OTHER_COLOUR,
    ]);
  });

  it("is a plain colour when there are no categories (an empty `match` is invalid)", () => {
    expect(colourExpression({})).toBe(OTHER_COLOUR);
  });
});

describe("building tooltip and popup", () => {
  it("explains the category on hover when the legend has an explanation", () => {
    expect(buildingSummary("osm", "known: tagged in OpenStreetMap")).toBe(
      "osm: known: tagged in OpenStreetMap",
    );
    expect(buildingSummary("other", undefined)).toBe("other");
  });

  it("lists the known facts and links to OpenStreetMap", () => {
    const details = buildingDetails({
      osm_id: "r456",
      building: "yes",
      residential: false,
      floors: 2,
      floors_source: "neighbours_300m",
      footprint_m2: 1234.4,
    });
    expect(details).toHaveTextContent(
      "OpenStreetMapr456TypeyesResidentialnoFloors2 (estimated)Ground area1234 m²",
    );
    expect(details.querySelector("a")).toHaveAttribute(
      "href",
      "https://www.openstreetmap.org/relation/456",
    );
  });

  it("shows text from OpenStreetMap as text, never as HTML", () => {
    const details = buildingDetails({ address: "<img src=x onerror=alert(1)>" });
    expect(details.querySelector("img")).toBeNull();
    expect(details).toHaveTextContent("<img src=x onerror=alert(1)>");
  });
});

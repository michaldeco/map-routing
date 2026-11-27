import { describe, expect, it } from "vitest";

import { OTHER_COLOUR, PALETTE } from "./buildings";
import { groupColours, locationDetails } from "./scenario";

describe("groupColours", () => {
  it("gives dense areas palette colours in legend order and outliers grey", () => {
    const items = ["area1", "area2", "outlier"].map((value) => ({
      value,
      count: 1,
      description: "",
    }));
    expect(groupColours(items)).toEqual({
      area1: PALETTE[0],
      area2: PALETTE[1],
      outlier: OTHER_COLOUR,
    });
  });
});

describe("location popup", () => {
  it("shows the visits, then the building", () => {
    const details = locationDetails({
      id: "b0001",
      osm_id: "w975585983",
      visits_per_week: 3,
      duration_min: 23.6,
      allowed_days: ["Mon", "Wed", "Fri"],
      floors: 2,
      floors_source: "osm",
    });
    expect(details).toHaveTextContent(
      "Locationb0001OpenStreetMapw975585983Visits per week3Visit length24 min" +
        "Allowed daysMon, Wed, FriFloors2 (known)",
    );
  });

  it("says 'any day' when no day is excluded, also from MapLibre's JSON text", () => {
    const allDays = JSON.stringify(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]);
    // MapLibre turns list properties into JSON text; the API type does not know that.
    const details = locationDetails({ allowed_days: allDays as unknown as string[] });
    expect(details).toHaveTextContent("Allowed daysany day");
  });
});

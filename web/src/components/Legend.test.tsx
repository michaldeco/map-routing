import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Legend } from "./Legend";

const LEGEND = {
  title: "Testville: 5,000 of 12,345 buildings (random sample)",
  subtitle: "Colour: why the building counts as residential or not.",
  items: [
    { value: "building=apartments", count: 3200, description: "OpenStreetMap names its type" },
    { value: "other", count: 1800, description: "less frequent values, grouped together" },
  ],
  footer: "Each dot is one building.",
  note: "",
};

describe("Legend", () => {
  it("shows the API's text with a coloured dot per category", () => {
    render(<Legend legend={LEGEND} colours={{ "building=apartments": "#4e79a7" }} />);
    const legend = screen.getByRole("region", { name: "Legend" });
    expect(legend).toHaveTextContent(LEGEND.title);
    expect(legend).toHaveTextContent(LEGEND.subtitle);
    expect(legend).toHaveTextContent("building=apartments (3,200) OpenStreetMap names its type");
    expect(legend).toHaveTextContent("other (1,800) less frequent values, grouped together");
    expect(legend).toHaveTextContent(LEGEND.footer);
    expect(screen.getByTestId("swatch-building=apartments")).toHaveStyle({
      background: "#4e79a7",
    });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a warning note", () => {
    render(<Legend legend={{ ...LEGEND, note: "Data is outdated." }} colours={{}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Data is outdated.");
  });
});

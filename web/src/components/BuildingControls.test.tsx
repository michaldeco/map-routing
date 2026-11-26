import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DEFAULT_BUILDING_OPTIONS, MAX_SEED } from "../api/client";
import { BuildingControls } from "./BuildingControls";

function renderControls(sampled = true) {
  const onChange = vi.fn();
  render(
    <BuildingControls options={DEFAULT_BUILDING_OPTIONS} onChange={onChange} sampled={sampled} />,
  );
  return onChange;
}

describe("BuildingControls", () => {
  it("changes one option at a time and keeps the others", async () => {
    const onChange = renderControls();
    await userEvent.selectOptions(screen.getByLabelText("Colour by"), "floors");
    expect(onChange).toHaveBeenLastCalledWith({ ...DEFAULT_BUILDING_OPTIONS, colourBy: "floors" });
    await userEvent.selectOptions(screen.getByLabelText("Buildings shown"), "all");
    expect(onChange).toHaveBeenLastCalledWith({ ...DEFAULT_BUILDING_OPTIONS, sample: "all" });
    await userEvent.selectOptions(screen.getByLabelText("Buildings shown"), "1000");
    expect(onChange).toHaveBeenLastCalledWith({ ...DEFAULT_BUILDING_OPTIONS, sample: 1000 });
    await userEvent.click(screen.getByLabelText("Residential buildings only"));
    expect(onChange).toHaveBeenLastCalledWith({
      ...DEFAULT_BUILDING_OPTIONS,
      residentialOnly: true,
    });
  });

  it("picks a new random seed, within the range the API accepts", async () => {
    vi.spyOn(Math, "random").mockReturnValue(0.999999999999);
    const onChange = renderControls();
    await userEvent.click(screen.getByRole("button", { name: "New sample" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...DEFAULT_BUILDING_OPTIONS, seed: MAX_SEED });
  });

  it("offers no new sample when all buildings are shown", () => {
    renderControls(false);
    expect(screen.getByRole("button", { name: "New sample" })).toBeDisabled();
  });
});

import { expect, test, type Page } from "@playwright/test";

import { BASEMAP_STYLE } from "../src/map/style";

const AREAS = [
  {
    slug: "testville",
    name: "Testville",
    data_date: "2026-11-21T20:21:02Z",
    bounds: { west: 22.9, south: 40.6, east: 22.97, north: 40.655 },
    has_buildings: true,
  },
  {
    slug: "otherville",
    name: "Otherville",
    data_date: null,
    bounds: { west: 17.0, south: 48.0, east: 17.1, north: 48.1 },
    has_buildings: false,
  },
];

function detail(area: (typeof AREAS)[number]) {
  const { west: w, south: s, east: e, north: n } = area.bounds;
  const ring = [
    [w, s],
    [e, s],
    [e, n],
    [w, n],
    [w, s],
  ];
  return { ...area, boundary: { type: "Polygon", coordinates: [ring] } };
}

/** Fake API and a plain basemap (no tiles), so the test needs no services or network. */
async function fakeBackend(page: Page) {
  await page.route("**/api/areas", (route) => route.fulfill({ json: AREAS }));
  for (const area of AREAS) {
    await page.route(`**/api/areas/${area.slug}`, (route) => route.fulfill({ json: detail(area) }));
  }
  await page.route(BASEMAP_STYLE, (route) =>
    route.fulfill({
      json: {
        version: 8,
        sources: {},
        layers: [{ id: "background", type: "background", paint: { "background-color": "#eee" } }],
      },
    }),
  );
}

test("the map loads and follows the chosen area", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await fakeBackend(page);

  await page.goto("/");
  const map = page.getByTestId("map");
  // Only true once MapLibre has fully loaded (its worker included) and drawn the area.
  await expect(map).toHaveAttribute("data-ready", "true");
  await expect(page.getByText("2026-11-21")).toBeVisible();

  await page.getByLabel("Area").selectOption("otherville");
  await expect(page.getByText("unknown (not fetched)")).toBeVisible();
  await expect(map).toHaveAttribute("data-ready", "true");
  expect(errors).toEqual([]);
});

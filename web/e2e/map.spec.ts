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

/** Latitude halfway between two others on the map. Web maps stretch north-south
 * (Web Mercator), so this is not the plain average. */
function mercatorMiddle(south: number, north: number) {
  const y = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
  const middle = (y(south) + y(north)) / 2;
  return ((2 * Math.atan(Math.exp(middle)) - Math.PI / 2) * 180) / Math.PI;
}

/** Two buildings: one at the centre of the area, where the map centres it, and one in a
 * corner. The legend category names the colouring, so a test can see it change. */
function buildings(area: (typeof AREAS)[number], colourBy: string) {
  const { west: w, south: s, east: e, north: n } = area.bounds;
  const centre = [(w + e) / 2, mercatorMiddle(s, n)];
  const feature = (osmId: string, coordinates: number[]) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates },
    properties: {
      osm_id: osmId,
      building: "apartments",
      residential: true,
      reason: "building=apartments",
      floors: 6,
      floors_source: "osm",
      footprint_m2: 420,
      address: "Testova 1",
      category: `by ${colourBy}`,
    },
  });
  return {
    type: "FeatureCollection",
    features: [feature("w1", centre), feature("w2", [w + 0.001, s + 0.001])],
    colour_by: colourBy,
    total: 2,
    shown: 2,
    sampled: false,
    seed: 0,
    legend: {
      title: `${area.name}: 2 of 2 buildings`,
      subtitle: `Colour: ${colourBy}`,
      items: [{ value: `by ${colourBy}`, count: 2, description: "test category" }],
      footer: "Each dot is one building.",
      note: "",
    },
  };
}

/** Fake API and a plain basemap (no tiles), so the test needs no services or network. */
async function fakeBackend(page: Page) {
  await page.route("**/api/areas", (route) => route.fulfill({ json: AREAS }));
  for (const area of AREAS) {
    await page.route(`**/api/areas/${area.slug}`, (route) => route.fulfill({ json: detail(area) }));
    await page.route(new RegExp(`/api/areas/${area.slug}/buildings\\?`), (route) => {
      const colourBy = new URL(route.request().url()).searchParams.get("colour_by") ?? "";
      return route.fulfill({ json: buildings(area, colourBy) });
    });
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

test("buildings are drawn, follow the colouring and show details on click", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await fakeBackend(page);

  await page.goto("/");
  const map = page.getByTestId("map");
  const legend = page.getByRole("region", { name: "Legend" });
  await expect(map).toHaveAttribute("data-buildings", "2");
  await expect(legend).toContainText("by reason (2) test category");

  await page.getByLabel("Colour by").selectOption("floors");
  await expect(legend).toContainText("by floors (2)");
  await expect(map).toHaveAttribute("data-buildings", "2");

  // The building at the area's centre is at the map's centre.
  await map.click();
  await expect(page.locator(".maplibregl-popup")).toContainText("AddressTestova 1");
  expect(errors).toEqual([]);
});

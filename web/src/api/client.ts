/**
 * Typed access to the map-routing API. Response types come from `types.ts`, which is
 * generated from the API's OpenAPI description (`make api-types`), so a change in the
 * backend models shows up here as a type error.
 */
import type { components } from "./types";

type Schemas = components["schemas"];
export type AreaSummary = Schemas["AreaSummary"];
export type AreaDetail = Schemas["AreaDetail"];
export type Bounds = Schemas["Bounds"];
export type Boundary = AreaDetail["boundary"];
export type BuildingCollection = Schemas["BuildingCollection"];
export type BuildingProperties = Schemas["BuildingProperties"];
export type Legend = Schemas["Legend"];
export type LegendItem = Schemas["LegendItem"];
/** Which imputation result the building colours show. */
export type ColourBy = BuildingCollection["colour_by"];

/** Largest sample seed the API accepts (`MAX_SEED` in `api/areas.py`). */
export const MAX_SEED = 2 ** 32 - 1;

/** What the buildings view asks the API for. */
export interface BuildingOptions {
  colourBy: ColourBy;
  /** How many buildings to show (a random sample), or all of them. */
  sample: number | "all";
  /** Picks the random sample: the same seed gives the same buildings. */
  seed: number;
  residentialOnly: boolean;
}

/** What the buildings view shows first (the API's defaults). */
export const DEFAULT_BUILDING_OPTIONS: BuildingOptions = {
  colourBy: "reason",
  sample: 5000,
  seed: 0,
  residentialOnly: false,
};

/** API URLs; a resource is identified by its URL (see `useResource`). */
export const apiPaths = {
  areas: "/api/areas",
  area: (slug: string) => `/api/areas/${encodeURIComponent(slug)}`,
  buildings: (slug: string, options: BuildingOptions) => {
    const query = new URLSearchParams({
      colour_by: options.colourBy,
      seed: String(options.seed),
      residential_only: String(options.residentialOnly),
    });
    if (options.sample === "all") query.set("all", "true");
    else query.set("sample", String(options.sample));
    return `/api/areas/${encodeURIComponent(slug)}/buildings?${query}`;
  },
};

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** GET a JSON resource; errors carry the API's `detail` message when there is one. */
export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal });
  if (!response.ok) {
    throw new ApiError(response.status, await errorDetail(response));
  }
  // `as T` tells the type checker what the JSON is (e.g. `AreaDetail`); it is not
  // checked when the code runs. That is acceptable because T comes from the types
  // generated from this same API (`make api-types`), and `make validate` fails if
  // they are out of date.
  return (await response.json()) as T;
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // not JSON, e.g. a proxy error page
  }
  return `${response.status} ${response.statusText}`.trim();
}

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

/** API URLs; a resource is identified by its URL (see `useResource`). */
export const apiPaths = {
  areas: "/api/areas",
  area: (slug: string) => `/api/areas/${encodeURIComponent(slug)}`,
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

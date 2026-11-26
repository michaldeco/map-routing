import { useState } from "react";

import {
  apiPaths,
  type AreaDetail,
  type AreaSummary,
  type BuildingCollection,
  DEFAULT_BUILDING_OPTIONS,
} from "./api/client";
import { useResource } from "./api/useResource";
import { AreaPanel } from "./components/AreaPanel";
import { BuildingControls } from "./components/BuildingControls";
import { Legend } from "./components/Legend";
import { MapView } from "./components/MapView";
import { categoryColours } from "./map/buildings";

/**
 * The whole page: control panel on the left, map on the right.
 *
 * A React component is a function that returns what to show, written as JSX (the
 * HTML-like syntax below; the build turns it into plain function calls). React calls
 * it again whenever its state changes and updates only the parts of the page that
 * differ. `{condition && <p>...</p>}` shows the paragraph only when the condition holds.
 *
 * The building options are state here, not in the controls, because two parts depend
 * on them: the controls show them and the request URL is built from them. Every
 * change gives a new URL, which `useResource` then loads.
 */
export function App() {
  const areas = useResource<AreaSummary[]>(apiPaths.areas);
  const [chosen, setChosen] = useState<string | null>(null);
  const [options, setOptions] = useState(DEFAULT_BUILDING_OPTIONS);
  const slug = chosen ?? areas.data?.[0]?.slug ?? null;
  // From the list, not the area's details, so buildings load in parallel with them.
  const hasBuildings = areas.data?.find((a) => a.slug === slug)?.has_buildings ?? false;
  const area = useResource<AreaDetail>(slug ? apiPaths.area(slug) : null);
  const buildings = useResource<BuildingCollection>(
    slug && hasBuildings ? apiPaths.buildings(slug, options) : null,
  );

  // While new buildings load (another colouring or sample), keep showing the last
  // ones of the same area instead of an empty map: with all buildings, a request takes
  // seconds. Never another area's buildings, and nothing old after a failed request.
  const [last, setLast] = useState<{ slug: string; data: BuildingCollection } | null>(null);
  if (slug && buildings.data && buildings.data !== last?.data) {
    // Updating state while rendering is React's way to remember a value from an
    // earlier render; React re-renders at once, before anything is shown.
    setLast({ slug, data: buildings.data });
  }
  const shown = buildings.data ?? (buildings.loading && last?.slug === slug ? last.data : null);

  return (
    <div className="app">
      <aside className="panel">
        <h1>map-routing</h1>
        {areas.loading && <p>Loading areas…</p>}
        {areas.error && <p role="alert">Cannot load areas: {areas.error}</p>}
        {areas.data && (
          <AreaPanel areas={areas.data} selected={slug} onSelect={setChosen} area={area.data} />
        )}
        {area.error && <p role="alert">Cannot load the area: {area.error}</p>}
        {hasBuildings && (
          <>
            <h2>Buildings</h2>
            <BuildingControls
              options={options}
              onChange={setOptions}
              sampled={shown?.sampled ?? true}
            />
            {buildings.loading && <p>Loading buildings…</p>}
            {buildings.error && <p role="alert">Cannot load buildings: {buildings.error}</p>}
            {shown && (
              <Legend
                legend={shown.legend}
                colours={categoryColours(shown.colour_by, shown.legend.items)}
              />
            )}
          </>
        )}
      </aside>
      <main className="map-container">
        <MapView
          boundary={area.data?.boundary ?? null}
          bounds={area.data?.bounds ?? null}
          buildings={shown}
        />
      </main>
    </div>
  );
}

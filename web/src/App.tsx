import { useState } from "react";

import { apiPaths, type AreaDetail, type AreaSummary } from "./api/client";
import { useResource } from "./api/useResource";
import { AreaPanel } from "./components/AreaPanel";
import { MapView } from "./components/MapView";

/**
 * The whole page: control panel on the left, map on the right.
 *
 * A React component is a function that returns what to show, written as JSX (the
 * HTML-like syntax below; the build turns it into plain function calls). React calls
 * it again whenever its state changes and updates only the parts of the page that
 * differ. `{condition && <p>...</p>}` shows the paragraph only when the condition holds.
 */
export function App() {
  const areas = useResource<AreaSummary[]>(apiPaths.areas);
  const [chosen, setChosen] = useState<string | null>(null);
  const slug = chosen ?? areas.data?.[0]?.slug ?? null;
  const area = useResource<AreaDetail>(slug ? apiPaths.area(slug) : null);

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
      </aside>
      <main className="map-container">
        <MapView boundary={area.data?.boundary ?? null} bounds={area.data?.bounds ?? null} />
      </main>
    </div>
  );
}

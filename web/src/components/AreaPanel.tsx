import type { AreaDetail, AreaSummary } from "../api/client";

interface Props {
  areas: AreaSummary[];
  selected: string | null;
  onSelect: (slug: string) => void;
  area?: AreaDetail;
}

/** Area choice and a few facts about the chosen area. */
export function AreaPanel({ areas, selected, onSelect, area }: Props) {
  if (areas.length === 0) {
    return (
      <p>
        No areas yet. Create one with <code>map-routing area define</code> and{" "}
        <code>area fetch</code>.
      </p>
    );
  }
  return (
    <section>
      <label className="field">
        <span>Area</span>
        <select value={selected ?? ""} onChange={(e) => onSelect(e.target.value)}>
          {areas.map((a) => (
            <option key={a.slug} value={a.slug}>
              {a.name}
            </option>
          ))}
        </select>
      </label>
      {area && (
        <dl className="facts">
          <dt>OSM data date</dt>
          <dd>{area.data_date ? area.data_date.slice(0, 10) : "unknown (not fetched)"}</dd>
          <dt>Imputed buildings</dt>
          <dd>{area.has_buildings ? "yes" : "no (run buildings extract and impute)"}</dd>
        </dl>
      )}
    </section>
  );
}

import type { Legend as LegendData } from "../api/client";

interface Props {
  legend: LegendData;
  /** Colour of each category (from `categoryColours`). */
  colours: Record<string, string>;
}

/** What the map shows: a title, what the colours mean, then one row per category with
 * its colour, name, number of buildings and a plain-language explanation. All text
 * comes from the API; only the colours are decided here. */
export function Legend({ legend, colours }: Props) {
  return (
    <section className="legend" aria-label="Legend">
      <h2>{legend.title}</h2>
      <p className="muted">{legend.subtitle}</p>
      {legend.note && <p role="alert">{legend.note}</p>}
      <ul>
        {legend.items.map((item) => (
          <li key={item.value}>
            <span
              className="swatch"
              style={{ background: colours[item.value] }}
              data-testid={`swatch-${item.value}`}
            />
            <span>
              <strong>{item.value}</strong> ({item.count.toLocaleString("en")})
              {item.description && <span className="muted"> {item.description}</span>}
            </span>
          </li>
        ))}
      </ul>
      {legend.footer && <p className="muted">{legend.footer}</p>}
    </section>
  );
}

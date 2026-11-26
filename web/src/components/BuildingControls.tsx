import { type BuildingOptions, type ColourBy, MAX_SEED } from "../api/client";

interface Props {
  options: BuildingOptions;
  onChange: (options: BuildingOptions) => void;
  /** Whether the buildings shown are a random sample (otherwise a new one is the same). */
  sampled: boolean;
}

/** Colouring options, in the order they appear. */
const COLOUR_BY_LABELS: [ColourBy, string][] = [
  ["reason", "Why residential or not"],
  ["residential", "Residential or not"],
  ["floors", "Floors"],
  ["floors-source", "Source of floors"],
];

/** Sample sizes offered. A few thousand dots show the pattern and stay fast; all
 * buildings of a city (100,000+) take a few seconds to load. */
const SAMPLE_SIZES = [1000, 5000, 20000] as const;

/** A new random seed, so "New sample" picks other buildings. */
function randomSeed(): number {
  return Math.floor(Math.random() * (MAX_SEED + 1));
}

/** Controls of the buildings view. Each change produces new options, and with them a
 * new API request (see `App`). */
export function BuildingControls({ options, onChange, sampled }: Props) {
  const set = (change: Partial<BuildingOptions>) => onChange({ ...options, ...change });
  return (
    <section>
      <label className="field">
        <span>Colour by</span>
        <select
          value={options.colourBy}
          onChange={(e) => set({ colourBy: e.target.value as ColourBy })}
        >
          {COLOUR_BY_LABELS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <div className="field-row">
        <label className="field">
          <span>Buildings shown</span>
          <select
            value={String(options.sample)}
            onChange={(e) => {
              const value = e.target.value;
              set({ sample: value === "all" ? "all" : Number(value) });
            }}
          >
            {SAMPLE_SIZES.map((n) => (
              <option key={n} value={n}>
                {n.toLocaleString("en")} (random sample)
              </option>
            ))}
            <option value="all">All (slower)</option>
          </select>
        </label>
        <button type="button" disabled={!sampled} onClick={() => set({ seed: randomSeed() })}>
          New sample
        </button>
      </div>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={options.residentialOnly}
          onChange={(e) => set({ residentialOnly: e.target.checked })}
        />
        Residential buildings only
      </label>
    </section>
  );
}

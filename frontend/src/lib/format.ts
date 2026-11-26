/** Display helpers. Rates are 0..1 in the API; people read percentages. */

export function pct(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? "–" : `${(value * 100).toFixed(digits)}%`;
}

/**
 * Fixed decimals rounded half-to-even, like Python's format(): 0.0625 -> "0.062".
 * The CLI and the PR comment print p-values with Python, so the dashboard must match.
 */
export function fixedEven(value: number, digits: number): string {
  const scale = 10 ** digits;
  const scaled = value * scale;
  const floor = Math.floor(scaled);
  const rest = scaled - floor;
  const rounded =
    Math.abs(rest - 0.5) < 1e-9 ? (floor % 2 === 0 ? floor : floor + 1) : Math.round(scaled);
  return (rounded / scale).toFixed(digits);
}

/** Small amounts stay readable: $0.00046 rather than $0.00 (same as the CLI). */
export function usd(value: number): string {
  return value >= 0.01 ? `$${value.toFixed(2)}` : `$${value.toFixed(5)}`;
}

export function num(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined ? "–" : value.toFixed(digits);
}

const RELATIVE = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
const STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["week", 7 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

export function ago(iso: string, now: Date = new Date()): string {
  const seconds = (new Date(iso).getTime() - now.getTime()) / 1000;
  for (const [unit, size] of STEPS) {
    if (Math.abs(seconds) >= size) return RELATIVE.format(Math.round(seconds / size), unit);
  }
  return "just now";
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** `sha256:1b01bf6534…` -> `1b01bf653477` */
export function shortHash(hash: string): string {
  return hash.replace(/^sha256:/, "").slice(0, 12);
}

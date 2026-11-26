/** What each metric means for a person, and how to print it. One place for every page. */

type Format = "pct" | "score" | "ratio" | "ms" | "int";

interface MetricInfo {
  label: string;
  help: string;
  format: Format;
}

const KNOWN: Record<string, MetricInfo> = {
  pass_rate: {
    label: "Pass rate",
    help: "Cases whose answer passed every gating check.",
    format: "pct",
  },
  schema_valid: {
    label: "Valid format",
    help: "Answers a program can read: JSON with an allowed category and a summary.",
    format: "pct",
  },
  label_exact: {
    label: "Correct category",
    help: "Readable answers whose category matches the human label.",
    format: "pct",
  },
  summary_format: {
    label: "Summary format",
    help: "One sentence, 5 to 40 words, not copied from the email.",
    format: "pct",
  },
  summary_similarity: {
    label: "Summary similarity",
    help: "Word overlap with the reference summary (information only).",
    format: "ratio",
  },
  summary_judge: {
    label: "Judge score",
    help: "Summary quality graded 1 to 5 by the AI judge (not gating yet).",
    format: "score",
  },
  macro_f1: {
    label: "Macro F1",
    help: "Average F1 over the categories: balances precision and recall.",
    format: "ratio",
  },
  error_rate: {
    label: "Error rate",
    help: "Cases that failed for technical reasons (excluded from quality).",
    format: "pct",
  },
  judge_error_rate: {
    label: "Judge error rate",
    help: "Summaries the judge could not grade.",
    format: "pct",
  },
  latency_ms_p50: { label: "Latency p50", help: "Median answer time, fresh calls only.", format: "ms" },
  latency_ms_p95: {
    label: "Latency p95",
    help: "95th percentile answer time, fresh calls only.",
    format: "ms",
  },
  tokens_total: { label: "Tokens", help: "Total tokens used by the app.", format: "int" },
  tokens_per_case: { label: "Tokens per case", help: "Average tokens per case.", format: "int" },
  judge_tokens_total: { label: "Judge tokens", help: "Tokens used by the judge.", format: "int" },
};

const SLICES: [RegExp, (label: string) => MetricInfo][] = [
  [
    /^label_exact\/(.+)$/,
    (l) => ({ label: `Correct: ${l}`, help: `Recall for “${l}”.`, format: "pct" }),
  ],
  [
    /^precision\/(.+)$/,
    (l) => ({ label: `Precision: ${l}`, help: `Answers “${l}” that were right.`, format: "pct" }),
  ],
  [/^f1\/(.+)$/, (l) => ({ label: `F1: ${l}`, help: `F1 score for “${l}”.`, format: "ratio" })],
];

export function metricInfo(name: string): MetricInfo {
  const known = KNOWN[name];
  if (known) return known;
  for (const [pattern, make] of SLICES) {
    const match = pattern.exec(name);
    if (match?.[1]) return make(match[1]);
  }
  return { label: name, help: "", format: "ratio" };
}

export function formatMetric(name: string, value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  switch (metricInfo(name).format) {
    case "pct":
      return `${(value * 100).toFixed(1)}%`;
    case "score":
      return value.toFixed(2);
    case "ratio":
      return value.toFixed(2);
    case "ms":
      return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`;
    case "int":
      return Math.round(value).toLocaleString("en");
  }
}

/** A comparison delta, as the CLI and the PR comment print it. */
export function formatDelta(delta: number | null, unit: string): string {
  if (delta === null) return "n/a";
  if (unit === "absolute") return `${delta >= 0 ? "+" : ""}${(delta * 100).toFixed(1)} pts`;
  return `${delta >= 0 ? "+" : ""}${(delta * 100).toFixed(0)}%`;
}

/** Main metrics first, slices (per category) after, alphabetically. */
export function sortMetrics(names: string[]): string[] {
  const order = Object.keys(KNOWN);
  const rank = (n: string) => {
    const i = order.indexOf(n);
    return i === -1 ? order.length : i;
  };
  return [...names].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

/** Metrics offered on the Trends page (they exist on every run). */
export const TREND_METRICS = [
  "pass_rate",
  "schema_valid",
  "label_exact",
  "summary_format",
  "summary_judge",
  "summary_similarity",
  "macro_f1",
  "latency_ms_p95",
  "tokens_total",
] as const;

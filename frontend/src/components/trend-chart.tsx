import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TrendPoint } from "@/api/client";
import { dateTime } from "@/lib/format";
import { formatMetric, metricInfo } from "@/lib/metrics";

/**
 * One metric over time (dataviz rules: one 2px series line in the accent hue, recessive
 * grid, a dashed reference line for the baseline, a crosshair tooltip).
 * Filled markers = fresh runs (real API calls); hollow = answers from the cache, which
 * cannot show drift.
 */
export function TrendChart({
  metric,
  points,
  connect = true,
  reference,
  referenceLabel,
}: {
  metric: string;
  points: TrendPoint[];
  /** false when points come from different prompt versions: no single trend joins them */
  connect?: boolean;
  reference?: number;
  referenceLabel?: string;
}) {
  const info = metricInfo(metric);
  const isRate = info.format === "pct";
  const data = points.map((p, i) => ({ ...p, index: i + 1 }));
  const values = data.map((p) => p.value).concat(reference !== undefined ? [reference] : []);
  const domain: [number, number] | ["auto", "auto"] = isRate
    ? [Math.max(0, Math.floor((Math.min(...values) - 0.05) * 10) / 10), 1]
    : ["auto", "auto"];

  return (
    <div className="h-72 w-full" role="img" aria-label={`${info.label} over the last ${points.length} runs`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 12, right: 16, bottom: 4, left: 4 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" strokeWidth={1} />
          <XAxis
            dataKey="index"
            tickLine={false}
            axisLine={{ stroke: "var(--border)" }}
            tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
            label={{ value: "run", position: "insideBottomRight", offset: -2, fill: "var(--muted-foreground)", fontSize: 11 }}
          />
          <YAxis
            domain={domain}
            width={56}
            tickLine={false}
            axisLine={false}
            tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
            tickFormatter={(v: number) => formatMetric(metric, v)}
          />
          {reference !== undefined && (
            <ReferenceLine
              y={reference}
              stroke="var(--muted-foreground)"
              strokeDasharray="4 4"
              label={{
                value: referenceLabel ?? "baseline",
                position: "insideTopLeft",
                fill: "var(--muted-foreground)",
                fontSize: 11,
              }}
            />
          )}
          <Tooltip
            cursor={{ stroke: "var(--muted-foreground)", strokeDasharray: "3 3" }}
            content={({ active, payload }) => {
              const p = payload?.[0]?.payload as (TrendPoint & { index: number }) | undefined;
              if (!active || !p) return null;
              return (
                <div className="rounded-lg border bg-popover px-3 py-2 text-xs shadow-md">
                  <div className="tabular text-sm font-medium">{formatMetric(metric, p.value)}</div>
                  <div className="mt-0.5 text-muted-foreground">
                    Run {p.index} · prompt {p.prompt_version} · {p.fresh ? "fresh calls" : "from cache"}
                  </div>
                  <div className="text-muted-foreground">{dateTime(p.started_at)}</div>
                  <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">{p.run_id}</div>
                </div>
              );
            }}
          />
          <Line
            type="linear"
            dataKey="value"
            stroke={connect ? "var(--series-1)" : "none"}
            strokeWidth={2}
            isAnimationActive={false}
            dot={(props: { cx?: number; cy?: number; payload?: TrendPoint; index?: number }) => (
              <circle
                key={props.index}
                cx={props.cx}
                cy={props.cy}
                r={4}
                strokeWidth={2}
                stroke="var(--series-1)"
                fill={props.payload?.fresh ? "var(--series-1)" : "var(--background)"}
              />
            )}
            activeDot={{ r: 6, stroke: "var(--background)", strokeWidth: 2, fill: "var(--series-1)" }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Tiny inline trend for tables (numbers only, no axes). */
export function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return <span className="text-xs text-muted-foreground">–</span>;
  const w = 72;
  const h = 20;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values
    .map((v, i) => `${(i / (values.length - 1)) * w},${h - 2 - ((v - min) / span) * (h - 4)}`)
    .join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden className="inline-block align-middle">
      <polyline points={points} fill="none" stroke="var(--series-1)" strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  );
}

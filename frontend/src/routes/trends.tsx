import { Activity, CircleCheck, Info } from "lucide-react";
import { useSearchParams } from "react-router";
import type { DriftReport, Schemas } from "@/api/client";
import { useDrift, useOverview, useTrend } from "@/api/queries";
import { CliHint, EmptyState, ErrorState, LoadingBlock, PageHeader } from "@/components/page";
import { Sparkline, TrendChart } from "@/components/trend-chart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDelta, formatMetric, metricInfo, TREND_METRICS } from "@/lib/metrics";
import { cn } from "@/lib/utils";

type MetricDrift = Schemas["MetricDrift"];
const ALL = "all";

function DriftStatus({ status }: { status: MetricDrift["status"] | DriftReport["status"] }) {
  if (status === "ok")
    return (
      <span className="inline-flex items-center gap-1.5 text-xs">
        <CircleCheck className="size-3.5 text-pass" aria-hidden /> Stable
      </span>
    );
  if (status === "drift")
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium">
        <Activity className="size-3.5 text-fail" aria-hidden /> Drifting
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <Info className="size-3.5" aria-hidden /> Not enough data
    </span>
  );
}

function DriftPanel({ drift }: { drift: DriftReport }) {
  return (
    <Card className="gap-0 py-0">
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 border-b px-5 py-3 [.border-b]:pb-3">
        <div>
          <CardTitle className="text-sm">Drift against baseline {drift.baseline_name}</CardTitle>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Only fresh runs of the same prompt, model and cases count: {drift.fresh_runs} fresh of{" "}
            {drift.comparable_runs} comparable runs.
          </p>
        </div>
        <DriftStatus status={drift.status} />
      </CardHeader>
      <CardContent className="px-2">
        {drift.status === "insufficient" && (
          <div className="m-3 rounded-lg bg-muted/50 p-3 text-sm text-muted-foreground">
            Drift needs at least a few fresh runs of the baseline prompt (cached answers cannot
            change). The daily monitor in GitHub Actions adds one per day; locally:
            <div className="mt-2">
              <CliHint command="uv run python -m regguard run -p v1 --baseline main --cases-from-baseline --no-judge --cache refresh -c ../examples/support-email-classifier/regguard.yaml" />
            </div>
          </div>
        )}
        {drift.metrics.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Metric</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Baseline</TableHead>
                <TableHead className="text-right">Moving avg.</TableHead>
                <TableHead className="text-right">Change</TableHead>
                <TableHead className="text-right">Runs</TableHead>
                <TableHead>Recent</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {drift.metrics.map((m) => (
                <TableRow key={m.metric} className={cn(m.status === "drift" && "bg-muted/40")}>
                  <TableCell title={m.message || metricInfo(m.metric).help}>
                    {metricInfo(m.metric).label}
                    {!m.gating && <span className="ml-1.5 text-xs text-muted-foreground">info</span>}
                  </TableCell>
                  <TableCell>
                    <DriftStatus status={m.status} />
                    {m.new_episode && <span className="ml-2 text-xs text-muted-foreground">new</span>}
                  </TableCell>
                  <TableCell className="tabular text-right text-muted-foreground">
                    {formatMetric(m.metric, m.reference)}
                  </TableCell>
                  <TableCell className="tabular text-right">{formatMetric(m.metric, m.moving_average)}</TableCell>
                  <TableCell className="tabular text-right">
                    {m.delta === null ? "–" : formatDelta(m.delta, m.unit)}
                  </TableCell>
                  <TableCell className="tabular text-right text-muted-foreground">{m.runs}</TableCell>
                  <TableCell>
                    <Sparkline values={m.values} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

export function Trends() {
  const [params, setParams] = useSearchParams();
  const overview = useOverview();
  const main = overview.data?.baselines.find((b) => b.name === "main");
  const metric = params.get("metric") ?? "pass_rate";
  // Default: the baseline's prompt. One line never joins different prompt versions.
  const defaultPrompt = main?.prompt_version ?? ALL;
  const prompt = params.get("prompt") ?? defaultPrompt;
  const trend = useTrend(metric, prompt === ALL ? undefined : prompt);
  const drift = useDrift();

  const set = (key: string, value: string, fallback: string) => {
    const next = new URLSearchParams(params);
    if (value === fallback) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  };

  const reference = main && (prompt === ALL || prompt === main.prompt_version)
    ? main.metrics[metric]
    : undefined;
  const all = trend.data ?? [];
  // Runs in ERROR scored only part of the cases; n = 0 means nothing was scored.
  const points = all.filter((p) => p.status !== "error" && p.n > 0);
  const hidden = all.length - points.length;

  return (
    <>
      <PageHeader
        title="Trends & drift"
        description="How each metric moves over time, and whether quality slides without any change."
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Select value={metric} onValueChange={(v) => set("metric", v, "pass_rate")}>
          <SelectTrigger className="w-52" aria-label="Metric">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {TREND_METRICS.map((m) => (
              <SelectItem key={m} value={m}>
                {metricInfo(m).label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={prompt} onValueChange={(v) => set("prompt", v, defaultPrompt)}>
          <SelectTrigger className="w-44" aria-label="Prompt version">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All prompt versions</SelectItem>
            {(overview.data?.recorded_prompt_versions ?? []).map((v) => (
              <SelectItem key={v} value={v}>
                Prompt {v}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Card className="mb-6 gap-2 py-4">
        <CardHeader className="px-5">
          <CardTitle className="text-sm">{metricInfo(metric).label}</CardTitle>
          <p className="text-xs text-muted-foreground">
            {metricInfo(metric).help} Filled points: fresh runs. Hollow: answers from the cache.
            {prompt === ALL && " Points from different prompt versions are not joined."}
            {hidden > 0 &&
              ` ${hidden} run${hidden > 1 ? "s" : ""} not shown (technical error or no case scored).`}
          </p>
        </CardHeader>
        <CardContent className="px-3">
          {trend.isError ? (
            <ErrorState error={trend.error} onRetry={trend.refetch} />
          ) : trend.isPending ? (
            <LoadingBlock className="h-72" />
          ) : points.length < 2 ? (
            <EmptyState icon={Activity} title="Not enough runs to draw a trend">
              This needs at least two recorded runs with this metric.
            </EmptyState>
          ) : (
            <TrendChart
              metric={metric}
              points={points}
              connect={prompt !== ALL}
              reference={reference}
              referenceLabel={main ? `baseline ${main.name} (${main.prompt_version})` : undefined}
            />
          )}
        </CardContent>
      </Card>

      {drift.isError ? (
        <ErrorState error={drift.error} onRetry={drift.refetch} />
      ) : drift.isPending ? (
        <LoadingBlock className="h-48" />
      ) : (
        <DriftPanel drift={drift.data} />
      )}
    </>
  );
}

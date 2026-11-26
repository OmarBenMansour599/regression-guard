import { CircleAlert, Info, Lock, TriangleAlert } from "lucide-react";
import { Link } from "react-router";
import type { Comparison, Schemas } from "@/api/client";
import { VerdictBadge } from "@/components/status";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { fixedEven } from "@/lib/format";
import { formatDelta, formatMetric, metricInfo } from "@/lib/metrics";
import { cn } from "@/lib/utils";

type MetricDelta = Schemas["MetricDelta"];
type Reason = Schemas["Reason"];
type CaseDiff = Schemas["CaseDiff"];

const VERDICT_SENTENCE: Record<Comparison["verdict"], string> = {
  pass: "No metric got significantly worse.",
  warn: "Something got worse, but not enough to block the change.",
  fail: "A significant regression: the gate blocks this change.",
  error: "No verdict: the candidate run failed for technical reasons.",
};

export function VerdictHeader({
  comparison,
  candidateLabel,
  referenceLabel,
}: {
  comparison: Comparison;
  candidateLabel: React.ReactNode;
  referenceLabel: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-4 rounded-xl border bg-card p-5">
      <VerdictBadge verdict={comparison.verdict} size="lg" />
      <div className="min-w-0 flex-1">
        <p className="font-medium">{VERDICT_SENTENCE[comparison.verdict]}</p>
        <p className="mt-0.5 text-sm text-muted-foreground">
          {candidateLabel} compared with {referenceLabel}
        </p>
      </div>
    </div>
  );
}

function ReasonIcon({ severity }: { severity: Reason["severity"] }) {
  if (severity === "fail") return <CircleAlert className="mt-0.5 size-4 shrink-0 text-fail" aria-label="Fail" />;
  if (severity === "warn")
    return <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warn" aria-label="Warning" />;
  return <Info className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-label="Note" />;
}

export function Reasons({ reasons }: { reasons: Reason[] }) {
  const decisive = reasons.filter((r) => r.severity !== "info");
  const notes = reasons.filter((r) => r.severity === "info");
  return (
    <div className="space-y-4">
      <ul className="space-y-2">
        {decisive.length === 0 && (
          <li className="text-sm text-muted-foreground">No metric crossed a threshold.</li>
        )}
        {decisive.map((r) => (
          <li key={`${r.code}-${r.metric}`} className="flex gap-2.5 text-sm">
            <ReasonIcon severity={r.severity} />
            <span>
              <code className="mr-1.5 rounded bg-muted px-1.5 py-0.5 text-xs">{r.code}</code>
              {r.message}
            </span>
          </li>
        ))}
      </ul>
      {notes.length > 0 && (
        <details className="group text-sm">
          <summary className="cursor-pointer text-muted-foreground select-none hover:text-foreground">
            {notes.length} note{notes.length > 1 ? "s" : ""}
          </summary>
          <ul className="mt-2 space-y-2">
            {notes.map((r) => (
              <li key={`${r.code}-${r.metric}`} className="flex gap-2.5 text-muted-foreground">
                <ReasonIcon severity="info" />
                <span>
                  <code className="mr-1.5 text-xs">{r.code}</code>
                  {r.message}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function Level({ metric }: { metric: MetricDelta }) {
  if (metric.level === "ok") return null;
  const critical = metric.level === "critical";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        critical ? "bg-fail/10 ring-fail/25" : "bg-warn/12 ring-warn/30",
      )}
    >
      {critical ? (
        <CircleAlert className="size-3 text-fail" aria-hidden />
      ) : (
        <TriangleAlert className="size-3 text-warn" aria-hidden />
      )}
      {critical ? "Critical" : "Warn"}
      {/* normal ink: grey on the tinted badge falls under the 4.5:1 minimum (axe) */}
      {!metric.gating && <span className="font-normal">(info)</span>}
    </span>
  );
}

export function MetricDeltas({ metrics }: { metrics: MetricDelta[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Metric</TableHead>
          <TableHead className="text-right">Baseline</TableHead>
          <TableHead className="text-right">Candidate</TableHead>
          <TableHead className="text-right">Change</TableHead>
          <TableHead className="text-right">
            <Tooltip>
              <TooltipTrigger className="cursor-help underline decoration-dotted underline-offset-4">
                −/+
              </TooltipTrigger>
              <TooltipContent>Cases that got worse / better (paired cases only)</TooltipContent>
            </Tooltip>
          </TableHead>
          <TableHead className="text-right">
            <Tooltip>
              <TooltipTrigger className="cursor-help underline decoration-dotted underline-offset-4">
                p
              </TooltipTrigger>
              <TooltipContent>Chance that the drop is random. Below 0.10 counts as evidence.</TooltipContent>
            </Tooltip>
          </TableHead>
          <TableHead>Level</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {metrics.map((m) => {
          const info = metricInfo(m.metric);
          return (
            <TableRow key={m.metric} className={cn(m.level !== "ok" && "bg-muted/40")}>
              <TableCell>
                <span title={info.help}>{info.label}</span>
                {!m.gating && <span className="ml-1.5 text-xs text-muted-foreground">info</span>}
              </TableCell>
              <TableCell className="tabular text-right text-muted-foreground">
                {formatMetric(m.metric, m.baseline)}
              </TableCell>
              <TableCell className="tabular text-right">{formatMetric(m.metric, m.candidate)}</TableCell>
              <TableCell className="tabular text-right">{formatDelta(m.delta, m.unit)}</TableCell>
              <TableCell className="tabular text-right text-muted-foreground">
                {m.regressed === null ? "–" : `${m.regressed}/${m.improved ?? 0}`}
              </TableCell>
              <TableCell className="tabular text-right text-muted-foreground">
                {m.p_value === null ? "–" : fixedEven(m.p_value, 3)}
              </TableCell>
              <TableCell>
                <Level metric={m} />
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

const CHANGE_LABEL: Record<CaseDiff["change"], string> = {
  regressed: "Regressed",
  improved: "Improved",
  still_pass: "Still pass",
  still_fail: "Still fail",
  new: "New",
  removed: "Removed",
  skipped: "Skipped",
};

export function ChangeLabel({ change }: { change: CaseDiff["change"] }) {
  const tone =
    change === "regressed"
      ? "bg-fail"
      : change === "improved"
        ? "bg-pass"
        : change === "still_fail"
          ? "bg-warn"
          : "bg-muted-foreground/40";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span aria-hidden className={cn("size-1.5 rounded-full", tone)} />
      {CHANGE_LABEL[change]}
    </span>
  );
}

/** Verdict + reasons + metrics in cards; the case list is left to the page. */
export function ComparisonPanels({ comparison }: { comparison: Comparison }) {
  return (
    <div className="grid gap-6">
      <Card className="gap-3 py-4">
        <CardHeader className="px-5">
          <CardTitle className="text-sm">Why this verdict</CardTitle>
        </CardHeader>
        <CardContent className="px-5">
          <Reasons reasons={comparison.reasons} />
        </CardContent>
      </Card>
      {comparison.metrics.length > 0 && (
        <Card className="gap-0 py-0">
          <CardHeader className="border-b px-5 py-3 [.border-b]:pb-3">
            <CardTitle className="text-sm">Metrics</CardTitle>
          </CardHeader>
          <CardContent className="px-2">
            <MetricDeltas metrics={comparison.metrics} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export function CriticalMark() {
  return (
    <span title="Critical case: must never regress" className="inline-flex">
      <Lock className="size-3.5 text-muted-foreground" aria-label="Critical case" />
    </span>
  );
}

export function RunLink({ runId }: { runId: string }) {
  return (
    <Link to={`/runs/${runId}`} className="font-mono text-xs underline-offset-4 hover:underline">
      {runId}
    </Link>
  );
}

import { ArrowLeft, ChevronDown, GitCompareArrows, TriangleAlert } from "lucide-react";
import { Fragment, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import type { RunDetail, Schemas } from "@/api/client";
import { ApiError } from "@/api/client";
import { useRun } from "@/api/queries";
import { CaseDetail } from "@/components/case-detail";
import { CriticalMark } from "@/components/comparison";
import { CliHint, EmptyState, ErrorState, LoadingBlock, PageHeader } from "@/components/page";
import { RunStatus, VerdictBadge } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Segmented } from "@/components/segmented";
import { dateTime, shortHash } from "@/lib/format";
import { formatMetric, metricInfo, sortMetrics } from "@/lib/metrics";
import { cn } from "@/lib/utils";

type CaseResult = Schemas["CaseResult"];
type Filter = "all" | "failing" | "errors";

const HEADLINE = ["pass_rate", "schema_valid", "label_exact", "summary_judge"];

function caseState(c: CaseResult): "pass" | "fail" | "invalid" | "error" {
  if (c.error) return "error";
  if (!c.parsed_output) return "invalid";
  return c.passed ? "pass" : "fail";
}

const STATE_TEXT = { pass: "Pass", fail: "Wrong", invalid: "Unreadable", error: "No answer" };
const STATE_DOT = {
  pass: "bg-pass",
  fail: "bg-fail",
  invalid: "bg-fail",
  error: "bg-error",
};

function Facts({ detail }: { detail: RunDetail }) {
  const m = detail.run.meta;
  const e = m.execution;
  const facts: [string, React.ReactNode][] = [
    ["Prompt", <>{m.prompt_version} <span className="font-mono text-xs text-muted-foreground">{shortHash(m.prompt_hash)}</span></>],
    ["Model", <span className="break-all">{m.model}{m.model_override ? " (override)" : ""}</span>],
    ["Dataset", <>{m.dataset_version} <span className="font-mono text-xs text-muted-foreground">{shortHash(m.dataset_hash)}</span></>],
    ["Started", dateTime(m.started_at)],
    ["Calls", `${e.api_calls} API · ${e.cache_hits} cached · ${e.retries} retries`],
    ["Code", m.git_sha ? <span className="font-mono text-xs">{m.git_sha.slice(0, 12)}</span> : "–"],
  ];
  if (m.judge) {
    facts.push(["Judge", `${String(m.judge.model ?? "")} · prompt ${String(m.judge.prompt_version ?? "")}`]);
  }
  return (
    <dl className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
      {facts.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="text-xs text-muted-foreground">{k}</dt>
          <dd className="mt-0.5">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function MetricsGrid({ detail }: { detail: RunDetail }) {
  const aggregates = detail.run.aggregates;
  const names = sortMetrics(Object.keys(aggregates));
  const headline = HEADLINE.filter((n) => n in aggregates);
  const rest = names.filter((n) => !headline.includes(n));
  const unreliable = detail.run.status === "error";
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {headline.map((name) => {
          const a = aggregates[name];
          const info = metricInfo(name);
          return (
            <div key={name} className="rounded-xl border p-4" title={info.help}>
              <div className="text-xs text-muted-foreground">{info.label}</div>
              <div
                className={cn(
                  "tabular mt-1 text-2xl font-semibold tracking-tight",
                  unreliable && "text-muted-foreground line-through decoration-muted-foreground/60",
                )}
              >
                {formatMetric(name, a?.value)}
              </div>
              <div className="text-xs text-muted-foreground">n = {a?.n ?? 0}</div>
            </div>
          );
        })}
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground select-none hover:text-foreground">
          All {names.length} metrics
        </summary>
        <dl className="mt-3 grid gap-x-8 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
          {rest.map((name) => (
            <div key={name} className="flex justify-between gap-4 border-b border-dashed py-1">
              <dt className="truncate text-muted-foreground" title={metricInfo(name).help}>
                {metricInfo(name).label}
              </dt>
              <dd className="tabular">{formatMetric(name, aggregates[name]?.value)}</dd>
            </div>
          ))}
        </dl>
      </details>
    </div>
  );
}

function Cases({ detail }: { detail: RunDetail }) {
  const [params, setParams] = useSearchParams();
  const filter = (params.get("cases") as Filter | null) ?? "all";
  const [open, setOpen] = useState<string | null>(params.get("case"));
  const cases = detail.run.cases;
  const labels = detail.run.meta.case_labels;
  const critical = new Set(detail.run.meta.critical_case_ids);

  const visible = cases.filter((c) => {
    const state = caseState(c);
    if (filter === "failing") return state === "fail" || state === "invalid";
    if (filter === "errors") return state === "error";
    return true;
  });
  const counts = {
    all: cases.length,
    failing: cases.filter((c) => ["fail", "invalid"].includes(caseState(c))).length,
    errors: cases.filter((c) => caseState(c) === "error").length,
  };
  const key = (c: CaseResult) => `${c.case_id}#${c.sample_idx}`;

  return (
    <Card className="gap-0 py-0">
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 border-b px-5 py-3 [.border-b]:pb-3">
        <CardTitle className="text-sm">Cases</CardTitle>
        <Segmented
          label="Show cases"
          value={filter}
          options={[
            { value: "all", label: `All ${counts.all}` },
            { value: "failing", label: `Failing ${counts.failing}` },
            { value: "errors", label: `Errors ${counts.errors}` },
          ]}
          onChange={(v) => {
            const next = new URLSearchParams(params);
            if (v === "all") next.delete("cases");
            else next.set("cases", v);
            setParams(next, { replace: true });
          }}
        />
      </CardHeader>
      <CardContent className="px-2">
        {visible.length === 0 ? (
          <p className="p-6 text-center text-sm text-muted-foreground">No case in this group.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>Case</TableHead>
                <TableHead>Expected</TableHead>
                <TableHead>Answer</TableHead>
                <TableHead>Result</TableHead>
                <TableHead className="text-right">Judge</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((c) => {
                const k = key(c);
                const isOpen = open === k || open === c.case_id;
                const state = caseState(c);
                const answer =
                  c.error?.type ?? (c.parsed_output ? String(c.parsed_output.category ?? "") : "—");
                return (
                  <Fragment key={k}>
                    <TableRow className="cursor-pointer" onClick={() => setOpen(isOpen ? null : k)}>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-6"
                          aria-expanded={isOpen}
                          aria-label={isOpen ? "Hide details" : "Show details"}
                        >
                          <ChevronDown
                            className={cn("transition-transform", isOpen && "rotate-180")}
                            aria-hidden
                          />
                        </Button>
                      </TableCell>
                      <TableCell>
                        <span className="inline-flex items-center gap-1.5 font-mono text-xs">
                          {c.case_id}
                          {c.sample_idx > 0 && `#${c.sample_idx}`}
                          {critical.has(c.case_id) && <CriticalMark />}
                        </span>
                      </TableCell>
                      <TableCell>{labels[c.case_id] ?? "–"}</TableCell>
                      <TableCell className={cn(state !== "pass" && "text-muted-foreground")}>
                        {answer}
                      </TableCell>
                      <TableCell>
                        <span className="inline-flex items-center gap-1.5 text-xs">
                          <span aria-hidden className={cn("size-1.5 rounded-full", STATE_DOT[state])} />
                          {STATE_TEXT[state]}
                        </span>
                      </TableCell>
                      <TableCell className="tabular text-right text-xs">
                        {c.judge?.score != null ? `${c.judge.score}/5` : "–"}
                      </TableCell>
                    </TableRow>
                    {isOpen && (
                      <TableRow className="hover:bg-transparent">
                        <TableCell colSpan={6} className="bg-muted/20 p-0 whitespace-normal">
                          <CaseDetail
                            result={c}
                            input={detail.inputs[c.case_id]?.email}
                            expected={detail.expected[c.case_id]}
                          />
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

export function Run() {
  const { runId } = useParams();
  const run = useRun(runId);

  if (run.isPending) return <LoadingBlock className="h-96" />;
  if (run.isError) {
    if (run.error instanceof ApiError && run.error.status === 404) {
      return (
        <EmptyState icon={TriangleAlert} title="Run not found">
          <p className="mb-3">It is not in the history database. Import the runs saved on disk:</p>
          <CliHint command="uv run python -m regguard history import" />
        </EmptyState>
      );
    }
    return <ErrorState error={run.error} onRetry={run.refetch} />;
  }

  const detail = run.data;
  const result = detail.run;
  const stored = detail.comparisons.at(-1);

  return (
    <>
      <Link
        to="/runs"
        className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden /> Runs
      </Link>
      <PageHeader
        title={`Run ${result.meta.prompt_version}`}
        description={<span className="font-mono text-xs">{result.meta.run_id}</span>}
        actions={
          <>
            <RunStatus status={result.status} />
            <Button variant="outline" size="sm" asChild>
              <Link to={`/compare?candidate=${result.meta.run_id}`}>
                <GitCompareArrows aria-hidden /> Compare
              </Link>
            </Button>
          </>
        }
      />

      {result.status === "error" && (
        <div
          role="alert"
          className="mb-6 flex gap-3 rounded-xl border border-error/40 bg-error/5 p-4 text-sm"
        >
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-error" aria-hidden />
          <div>
            <p className="font-medium">This run failed for technical reasons: no quality verdict.</p>
            <p className="mt-0.5 text-muted-foreground">{result.error}</p>
          </div>
        </div>
      )}

      <div className="grid gap-6">
        <Card className="gap-4 py-5">
          <CardContent className="px-5">
            <Facts detail={detail} />
          </CardContent>
        </Card>

        {stored && (
          <Link
            to={`/compare?candidate=${result.meta.run_id}${stored.baseline_name ? `&baseline=${stored.baseline_name}` : `&against=${stored.baseline_run_id}`}`}
            className="flex flex-wrap items-center gap-3 rounded-xl border p-4 text-sm hover:bg-accent/40"
          >
            <VerdictBadge verdict={stored.verdict} />
            <span>
              Recorded comparison against{" "}
              {stored.baseline_name ? `baseline ${stored.baseline_name}` : stored.baseline_run_id}
            </span>
            <span className="ml-auto text-xs text-muted-foreground">Open the comparison →</span>
          </Link>
        )}

        <MetricsGrid detail={detail} />

        {detail.notes.length > 0 && (
          <p className="text-xs text-muted-foreground">{detail.notes.join(" ")}</p>
        )}

        <Cases detail={detail} />
      </div>
    </>
  );
}

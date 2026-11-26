import { Activity, ArrowUpRight, Database, History, Info, Pin, type LucideIcon } from "lucide-react";
import { Link } from "react-router";
import type { DriftReport, RunSummary } from "@/api/client";
import { useDrift, useOverview, useRuns } from "@/api/queries";
import { CliHint, EmptyState, ErrorState, LoadingBlock, PageHeader } from "@/components/page";
import { RunStatus, VerdictBadge } from "@/components/status";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ago, pct, shortHash } from "@/lib/format";
import { cn } from "@/lib/utils";

function Tile({
  label,
  icon: Icon,
  to,
  children,
  foot,
}: {
  label: string;
  icon: LucideIcon;
  to?: string;
  children: React.ReactNode;
  foot?: React.ReactNode;
}) {
  const body = (
    <Card
      className={cn(
        "h-full gap-3 py-4 transition-colors",
        to && "hover:bg-accent/40 focus-visible:ring-2",
      )}
    >
      <CardHeader className="flex flex-row items-center justify-between gap-2 px-4">
        <CardTitle className="text-xs font-medium text-muted-foreground">{label}</CardTitle>
        {to ? (
          <ArrowUpRight className="size-3.5 text-muted-foreground" aria-hidden />
        ) : (
          <Icon className="size-3.5 text-muted-foreground" aria-hidden />
        )}
      </CardHeader>
      <CardContent className="space-y-1 px-4">
        <div className="text-2xl font-semibold tracking-tight">{children}</div>
        {foot && <div className="text-xs text-muted-foreground">{foot}</div>}
      </CardContent>
    </Card>
  );
  return to ? (
    <Link to={to} className="rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {body}
    </Link>
  ) : (
    body
  );
}

function DriftValue({ drift }: { drift: DriftReport }) {
  if (drift.status === "insufficient") {
    return (
      <span className="inline-flex items-center gap-2 text-base font-medium">
        <Info className="size-4 text-muted-foreground" aria-hidden /> Not enough data
      </span>
    );
  }
  return drift.status === "ok" ? (
    <VerdictBadge verdict="pass" size="lg" />
  ) : (
    <span className="inline-flex items-center gap-2 text-base font-medium">
      <Activity className="size-4 text-fail" aria-hidden /> Drifting
    </span>
  );
}

/** A run in ERROR scored only the cases that got an answer: never show that as a real score. */
export function PassRate({ run }: { run: RunSummary }) {
  if (run.status !== "error") return <>{pct(run.metrics.pass_rate)}</>;
  return (
    <span
      className="text-muted-foreground/60 line-through decoration-muted-foreground/40"
      title="Not a quality score: this run failed for technical reasons, so only part of the cases were scored."
    >
      {pct(run.metrics.pass_rate)}
    </span>
  );
}

function latestPerPrompt(runs: RunSummary[]): RunSummary[] {
  const seen = new Map<string, RunSummary>();
  for (const run of runs) if (!seen.has(run.prompt_version)) seen.set(run.prompt_version, run);
  return [...seen.values()].sort((a, b) => a.prompt_version.localeCompare(b.prompt_version));
}

function RunsTable({ runs }: { runs: RunSummary[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Run</TableHead>
          <TableHead>Prompt</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Pass rate</TableHead>
          <TableHead>Verdict</TableHead>
          <TableHead className="text-right">When</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => (
          <TableRow key={run.run_id}>
            <TableCell>
              <Link
                to={`/runs/${run.run_id}`}
                className="font-mono text-xs underline-offset-4 hover:underline"
              >
                {run.run_id}
              </Link>
            </TableCell>
            <TableCell>{run.prompt_version}</TableCell>
            <TableCell>
              <RunStatus status={run.status} />
            </TableCell>
            <TableCell className="tabular text-right">
              <PassRate run={run} />
            </TableCell>
            <TableCell>
              {run.verdict ? (
                <VerdictBadge verdict={run.verdict} />
              ) : (
                <span className="text-xs text-muted-foreground">–</span>
              )}
            </TableCell>
            <TableCell className="text-right text-xs text-muted-foreground">
              <time dateTime={run.started_at} title={run.started_at}>
                {ago(run.started_at)}
              </time>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function Overview() {
  const overview = useOverview();
  const runs = useRuns({ limit: 50 });
  const drift = useDrift();

  if (overview.isError) return <ErrorState error={overview.error} onRetry={overview.refetch} />;

  const app = overview.data;
  const items = runs.data?.items ?? [];
  const main = app?.baselines.find((b) => b.name === "main") ?? app?.baselines[0];
  const latestVerdict = items.find((r) => r.verdict);
  const config = "../examples/support-email-classifier/regguard.yaml";

  return (
    <>
      <PageHeader
        title="Overview"
        description={
          app ? (
            <>
              <span className="text-foreground">{app.name}</span> · dataset{" "}
              {app.dataset ? `${app.dataset.version}, ${app.dataset.cases} cases` : "unavailable"} ·{" "}
              {app.prompts.length} prompt versions
            </>
          ) : (
            "Loading…"
          )
        }
      />

      <section aria-label="Summary" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {!app || runs.isPending ? (
          Array.from({ length: 4 }, (_, i) => <LoadingBlock key={i} className="h-[118px]" />)
        ) : (
          <>
            <Tile
              label="Latest verdict"
              icon={History}
              to={latestVerdict ? `/runs/${latestVerdict.run_id}` : undefined}
              foot={
                latestVerdict
                  ? `${latestVerdict.prompt_version} vs ${latestVerdict.verdict_baseline ?? "run"} · ${ago(latestVerdict.started_at)}`
                  : "No comparison recorded yet"
              }
            >
              {latestVerdict?.verdict ? (
                <VerdictBadge verdict={latestVerdict.verdict} size="lg" />
              ) : (
                "–"
              )}
            </Tile>
            <Tile
              label={`Baseline ${main?.name ?? ""}`}
              icon={Pin}
              to="/baselines"
              foot={
                main
                  ? `prompt ${main.prompt_version} · ${shortHash(main.prompt_hash)} · ${ago(main.promoted_at)}`
                  : "No baseline promoted"
              }
            >
              <span className="tabular">{main ? pct(main.metrics.pass_rate) : "–"}</span>
              {main && (
                <span className="ml-1.5 text-sm font-normal text-muted-foreground">pass rate</span>
              )}
            </Tile>
            <Tile
              label="Drift"
              icon={Activity}
              to="/trends"
              foot={
                drift.data
                  ? `${drift.data.fresh_runs} fresh of ${drift.data.comparable_runs} comparable runs`
                  : drift.isError
                    ? "Unavailable"
                    : "…"
              }
            >
              {drift.data ? <DriftValue drift={drift.data} /> : "–"}
            </Tile>
            <Tile
              label="Runs recorded"
              icon={Database}
              to="/runs"
              foot={items[0] ? `last run ${ago(items[0].started_at)}` : "None yet"}
            >
              <span className="tabular">{runs.data?.total ?? 0}</span>
            </Tile>
          </>
        )}
      </section>

      {runs.isError && (
        <div className="mt-6">
          <ErrorState error={runs.error} onRetry={runs.refetch} />
        </div>
      )}

      {runs.data && items.length === 0 && (
        <div className="mt-6">
          <EmptyState icon={History} title="No runs recorded yet">
            <p className="mb-3">Run an evaluation, or import the runs saved before Phase 6:</p>
            <CliHint command="uv run python -m regguard history import" />
          </EmptyState>
        </div>
      )}

      {items.length > 0 && (
        <div className="mt-6 grid items-start gap-6 lg:grid-cols-3">
          <Card className="gap-0 py-0 lg:col-span-1">
            <CardHeader className="border-b px-4 py-3 [.border-b]:pb-3">
              <CardTitle className="text-sm">Prompt versions</CardTitle>
            </CardHeader>
            <CardContent className="divide-y px-0">
              {latestPerPrompt(items).map((run) => (
                <Link
                  key={run.prompt_version}
                  to={`/runs/${run.run_id}`}
                  className="flex items-center justify-between gap-3 px-4 py-3 text-sm hover:bg-accent/40"
                >
                  <div>
                    <div className="font-medium">{run.prompt_version}</div>
                    <div className="text-xs text-muted-foreground">
                      latest run {ago(run.started_at)}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="tabular text-xs text-muted-foreground">
                      <PassRate run={run} />
                    </span>
                    {run.verdict ? (
                      <VerdictBadge verdict={run.verdict} />
                    ) : (
                      <RunStatus status={run.status} />
                    )}
                  </div>
                </Link>
              ))}
            </CardContent>
          </Card>

          <Card className="gap-0 py-0 lg:col-span-2">
            <CardHeader className="flex flex-row items-center justify-between border-b px-4 py-3 [.border-b]:pb-3">
              <CardTitle className="text-sm">Recent runs</CardTitle>
              <Link to="/runs" className="text-xs text-muted-foreground hover:text-foreground">
                All runs →
              </Link>
            </CardHeader>
            <CardContent className="px-2">
              <RunsTable runs={items.slice(0, 10)} />
            </CardContent>
          </Card>
        </div>
      )}

      {app && app.notes.length > 0 && (
        <ul className="mt-6 space-y-1 text-xs text-muted-foreground">
          {app.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}

      <div className="mt-8 max-w-xl">
        <CliHint command={`uv run python -m regguard run -p v1 --baseline main -c ${config}`}>
          The dashboard is read-only. To evaluate a prompt against the baseline:
        </CliHint>
      </div>
    </>
  );
}

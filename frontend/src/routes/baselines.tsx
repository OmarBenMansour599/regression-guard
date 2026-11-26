import { Pin } from "lucide-react";
import { Link } from "react-router";
import type { Schemas } from "@/api/client";
import { useOverview } from "@/api/queries";
import { RunLink } from "@/components/comparison";
import { CliHint, EmptyState, ErrorState, LoadingBlock, PageHeader } from "@/components/page";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ago, dateTime, shortHash } from "@/lib/format";
import { formatMetric, metricInfo } from "@/lib/metrics";

type Baseline = Schemas["BaselineSummary"];
type Dataset = Schemas["DatasetInfo"];
const CONFIG = "../examples/support-email-classifier/regguard.yaml";
const KEY_METRICS = ["pass_rate", "schema_valid", "label_exact", "summary_judge"];

function BaselineCard({ baseline }: { baseline: Baseline }) {
  return (
    <Card className="gap-4 py-5">
      <CardHeader className="flex flex-row items-start justify-between gap-3 px-5">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <Pin className="size-4 text-muted-foreground" aria-hidden /> {baseline.name}
          </CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">
            Prompt {baseline.prompt_version} · promoted {ago(baseline.promoted_at)} (
            {dateTime(baseline.promoted_at)})
          </p>
        </div>
        <Link
          to={baseline.name === "main" ? "/compare" : `/compare?baseline=${baseline.name}`}
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          Compare a run →
        </Link>
      </CardHeader>
      <CardContent className="grid gap-5 px-5">
        <div className="grid gap-3 sm:grid-cols-4">
          {KEY_METRICS.filter((m) => m in baseline.metrics).map((m) => (
            <div key={m} className="rounded-lg border p-3" title={metricInfo(m).help}>
              <div className="text-xs text-muted-foreground">{metricInfo(m).label}</div>
              <div className="tabular mt-0.5 text-lg font-semibold">
                {formatMetric(m, baseline.metrics[m])}
              </div>
            </div>
          ))}
        </div>
        <dl className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs text-muted-foreground">Source run</dt>
            <dd>
              <RunLink runId={baseline.source_run_id} />
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Model</dt>
            <dd className="break-all">{baseline.model}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Prompt fingerprint</dt>
            <dd className="font-mono text-xs">{shortHash(baseline.prompt_hash)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Dataset · cases</dt>
            <dd>
              {baseline.dataset_version} · {baseline.cases}
            </dd>
          </div>
          {baseline.git_sha && (
            <div>
              <dt className="text-xs text-muted-foreground">Code at promotion</dt>
              <dd className="font-mono text-xs">{baseline.git_sha.slice(0, 12)}</dd>
            </div>
          )}
          {baseline.note && (
            <div className="sm:col-span-2">
              <dt className="text-xs text-muted-foreground">Note</dt>
              <dd>{baseline.note}</dd>
            </div>
          )}
        </dl>
      </CardContent>
    </Card>
  );
}

/** Horizontal bars, one hue: counts are the data, so they are labelled directly. */
function Distribution({ title, counts }: { title: string; counts: Record<string, number> }) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const max = Math.max(1, ...entries.map(([, n]) => n));
  return (
    <div>
      <h3 className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">{title}</h3>
      <ul className="space-y-1.5">
        {entries.map(([name, n]) => (
          <li key={name} className="grid grid-cols-[6rem_1fr_2rem] items-center gap-3 text-sm">
            <span className="truncate">{name}</span>
            <span className="h-2 rounded-full bg-muted">
              <span
                className="block h-2 rounded-full bg-series-1"
                style={{ width: `${(n / max) * 100}%` }}
              />
            </span>
            <span className="tabular text-right text-muted-foreground">{n}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DatasetCard({ dataset }: { dataset: Dataset }) {
  return (
    <Card className="gap-4 py-5">
      <CardHeader className="px-5">
        <CardTitle className="text-sm">Golden dataset {dataset.version}</CardTitle>
        <p className="text-xs text-muted-foreground">
          {dataset.cases} human-labelled cases · {dataset.critical} critical · fingerprint{" "}
          <span className="font-mono">{shortHash(dataset.content_hash)}</span>
        </p>
      </CardHeader>
      <CardContent className="grid gap-6 px-5 sm:grid-cols-2">
        <Distribution title="Categories" counts={dataset.labels} />
        <Distribution title="Difficulty" counts={dataset.difficulty} />
      </CardContent>
    </Card>
  );
}

export function Baselines() {
  const overview = useOverview();
  if (overview.isError) return <ErrorState error={overview.error} onRetry={overview.refetch} />;
  if (overview.isPending) return <LoadingBlock className="h-96" />;

  const app = overview.data;
  const baselineHashes = new Map(app.baselines.map((b) => [b.prompt_hash, b.name]));

  return (
    <>
      <PageHeader
        title="Baselines & prompts"
        description="The pinned reference runs, every prompt version, and the golden dataset."
      />
      <div className="grid gap-6">
        {app.baselines.length === 0 ? (
          <EmptyState icon={Pin} title="No baseline promoted yet">
            <p className="mb-3">Promote a trusted run as the reference for every comparison:</p>
            <CliHint command={`uv run python -m regguard baseline promote <run-id> -c ${CONFIG}`} />
          </EmptyState>
        ) : (
          app.baselines.map((b) => <BaselineCard key={b.name} baseline={b} />)
        )}

        <Card className="gap-0 py-0">
          <CardHeader className="border-b px-5 py-3 [.border-b]:pb-3">
            <CardTitle className="text-sm">Prompt versions</CardTitle>
          </CardHeader>
          <CardContent className="px-2">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Version</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead>Fingerprint</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead className="text-right">Runs</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {app.prompts.map((p) => {
                  const pinned = baselineHashes.get(p.content_hash);
                  const recorded = app.recorded_prompt_versions.includes(p.version);
                  return (
                    <TableRow key={p.version}>
                      <TableCell className="font-medium">
                        {p.version}
                        {pinned && (
                          <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs font-normal">
                            <Pin className="size-3" aria-hidden /> {pinned}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-sm break-all">{p.model}</TableCell>
                      <TableCell className="font-mono text-xs">{shortHash(p.content_hash)}</TableCell>
                      <TableCell className="max-w-sm text-sm whitespace-normal text-muted-foreground">
                        {p.description || "–"}
                      </TableCell>
                      <TableCell className="text-right text-xs">
                        {recorded ? (
                          <Link to={`/runs?prompt=${p.version}`} className="underline-offset-4 hover:underline">
                            View runs
                          </Link>
                        ) : (
                          <span className="text-muted-foreground">none yet</span>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        {app.dataset && <DatasetCard dataset={app.dataset} />}

        <CliHint command={`uv run python -m regguard baseline promote <run-id> --replace -c ${CONFIG}`}>
          Baselines change only through the CLI, in a reviewed pull request. To pin a new reference:
        </CliHint>
      </div>
    </>
  );
}

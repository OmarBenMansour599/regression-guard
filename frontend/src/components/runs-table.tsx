import { useNavigate } from "react-router";
import type { RunSummary } from "@/api/client";
import { RunStatus, VerdictBadge } from "@/components/status";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ago, dateTime, pct } from "@/lib/format";
import { cn } from "@/lib/utils";

/** A run in ERROR scored only the cases that got an answer: never show that as a real score. */
export function Score({
  run,
  metric,
}: {
  run: Pick<RunSummary, "status" | "metrics">;
  metric: string;
}) {
  const value = pct(run.metrics[metric]);
  if (run.status !== "error") return <>{value}</>;
  return (
    <span
      className="text-muted-foreground/60 line-through decoration-muted-foreground/40"
      title="Not a quality score: this run failed for technical reasons, so only part of the cases were scored."
    >
      {value}
    </span>
  );
}

export function PassRate({ run }: { run: Pick<RunSummary, "status" | "metrics"> }) {
  return <Score run={run} metric="pass_rate" />;
}

/** Whole rows are clickable; the run id stays a real link (keyboard, middle-click). */
export function RunsTable({ runs, detailed = false }: { runs: RunSummary[]; detailed?: boolean }) {
  const navigate = useNavigate();
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Run</TableHead>
          <TableHead>Prompt</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Pass rate</TableHead>
          {detailed && <TableHead className="text-right">Valid format</TableHead>}
          {detailed && <TableHead className="text-right">Calls</TableHead>}
          <TableHead>Verdict</TableHead>
          <TableHead className="text-right">When</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => (
          <TableRow
            key={run.run_id}
            className="cursor-pointer"
            onClick={(event) => {
              if ((event.target as HTMLElement).closest("a")) return;
              navigate(`/runs/${run.run_id}`);
            }}
          >
            <TableCell>
              <a
                href={`/runs/${run.run_id}`}
                onClick={(event) => {
                  if (event.metaKey || event.ctrlKey || event.button !== 0) return;
                  event.preventDefault();
                  navigate(`/runs/${run.run_id}`);
                }}
                className="font-mono text-xs underline-offset-4 hover:underline"
              >
                {run.run_id}
              </a>
            </TableCell>
            <TableCell>{run.prompt_version}</TableCell>
            <TableCell>
              <RunStatus status={run.status} />
            </TableCell>
            <TableCell className="tabular text-right">
              <PassRate run={run} />
            </TableCell>
            {detailed && (
              <TableCell className="tabular text-right">
                <Score run={run} metric="schema_valid" />
              </TableCell>
            )}
            {detailed && (
              <TableCell
                className="tabular text-right text-xs text-muted-foreground"
                title={`${run.api_calls} API calls, ${run.cache_hits} answers from the cache`}
              >
                {run.api_calls === 0 ? "cached" : run.api_calls}
              </TableCell>
            )}
            <TableCell>
              {run.verdict ? (
                <VerdictBadge verdict={run.verdict} />
              ) : (
                <span className="text-xs text-muted-foreground">–</span>
              )}
            </TableCell>
            <TableCell
              className={cn("text-right text-xs text-muted-foreground", detailed && "whitespace-nowrap")}
            >
              <time dateTime={run.started_at} title={dateTime(run.started_at)}>
                {ago(run.started_at)}
              </time>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

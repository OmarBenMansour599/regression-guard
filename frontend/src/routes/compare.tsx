import { ArrowRight, GitCompareArrows } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";
import type { RunDetail, RunSummary, Schemas } from "@/api/client";
import { useCompare, useOverview, useRun, useRuns } from "@/api/queries";
import { Answer, Checks, EmailText, Section } from "@/components/case-detail";
import {
  ChangeLabel,
  ComparisonPanels,
  CriticalMark,
  RunLink,
  VerdictHeader,
} from "@/components/comparison";
import { EmptyState, ErrorState, LoadingBlock, PageHeader } from "@/components/page";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ago } from "@/lib/format";
import { cn } from "@/lib/utils";

type CaseDiff = Schemas["CaseDiff"];

function runOption(run: RunSummary): string {
  return `${run.prompt_version} · ${ago(run.started_at)}${run.status === "error" ? " · error" : ""}`;
}

function Pickers({ runs, baselines }: { runs: RunSummary[]; baselines: string[] }) {
  const [params, setParams] = useSearchParams();
  const candidate = params.get("candidate") ?? "";
  const against = params.get("against");
  const reference = against ? `run:${against}` : `baseline:${params.get("baseline") ?? "main"}`;

  const set = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    setParams(next);
  };

  return (
    <div className="mb-6 flex flex-wrap items-center gap-2">
      <Select value={candidate} onValueChange={(v) => set({ candidate: v })}>
        <SelectTrigger className="w-72" aria-label="Candidate run">
          <SelectValue placeholder="Candidate run" />
        </SelectTrigger>
        <SelectContent>
          {runs.map((r) => (
            <SelectItem key={r.run_id} value={r.run_id}>
              {runOption(r)}
              <span className="ml-1 font-mono text-[11px] text-muted-foreground">
                {r.run_id.slice(-6)}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <span className="px-1 text-sm text-muted-foreground">against</span>
      <Select
        value={reference}
        onValueChange={(v) => {
          const [kind, id] = v.split(/:(.*)/s) as [string, string];
          set(kind === "run" ? { against: id, baseline: null } : { baseline: id, against: null });
        }}
      >
        <SelectTrigger className="w-72" aria-label="Reference">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectLabel>Baselines</SelectLabel>
            {baselines.map((b) => (
              <SelectItem key={b} value={`baseline:${b}`}>
                Baseline {b}
              </SelectItem>
            ))}
          </SelectGroup>
          <SelectGroup>
            <SelectLabel>Another run</SelectLabel>
            {runs
              .filter((r) => r.run_id !== candidate)
              .map((r) => (
                <SelectItem key={r.run_id} value={`run:${r.run_id}`}>
                  {runOption(r)}
                  <span className="ml-1 font-mono text-[11px] text-muted-foreground">
                    {r.run_id.slice(-6)}
                  </span>
                </SelectItem>
              ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    </div>
  );
}

function SideBySide({
  diff,
  candidate,
  reference,
}: {
  diff: CaseDiff;
  candidate: RunDetail | undefined;
  reference: RunDetail | undefined;
}) {
  const find = (d: RunDetail | undefined) => d?.run.cases.find((c) => c.case_id === diff.case_id);
  const cand = find(candidate);
  const ref = find(reference);
  const input = candidate?.inputs[diff.case_id]?.email ?? reference?.inputs[diff.case_id]?.email;
  const expected = candidate?.expected[diff.case_id] ?? reference?.expected[diff.case_id];
  return (
    <div className="grid gap-5 p-4 lg:grid-cols-[1.2fr_1fr_1fr]">
      <div className="grid content-start gap-4">
        <Section title="Email">
          <EmailText text={input} />
        </Section>
        <Section title="Expected">
          <p className="text-sm">
            {expected ? String(expected.category ?? "") : <span className="text-muted-foreground">–</span>}
          </p>
        </Section>
      </div>
      <Section title="Reference answer" className="rounded-lg border p-3">
        {reference ? <Answer result={ref} /> : <p className="text-sm text-muted-foreground">Run not in the history database.</p>}
        {ref && <Checks result={ref} />}
      </Section>
      <Section
        title="Candidate answer"
        className={cn(
          "rounded-lg border p-3",
          diff.change === "regressed" && "border-fail/40",
          diff.change === "improved" && "border-pass/40",
        )}
      >
        <Answer result={cand} />
        {cand && <Checks result={cand} />}
      </Section>
    </div>
  );
}

type CaseFilter = "changed" | "all";

function CaseList({
  diffs,
  candidate,
  reference,
}: {
  diffs: CaseDiff[];
  candidate: RunDetail | undefined;
  reference: RunDetail | undefined;
}) {
  const [filter, setFilter] = useState<CaseFilter>("changed");
  const changed = diffs.filter((d) => d.change === "regressed" || d.change === "improved");
  const order: Record<CaseDiff["change"], number> = {
    regressed: 0,
    improved: 1,
    still_fail: 2,
    skipped: 3,
    new: 4,
    removed: 5,
    still_pass: 6,
  };
  const shown = (filter === "changed" ? changed : diffs)
    .slice()
    .sort((a, b) => order[a.change] - order[b.change] || a.case_id.localeCompare(b.case_id));

  return (
    <Card className="gap-0 py-0">
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 border-b px-5 py-3 [.border-b]:pb-3">
        <CardTitle className="text-sm">Cases</CardTitle>
        <Tabs value={filter} onValueChange={(v) => setFilter(v as CaseFilter)}>
          <TabsList>
            <TabsTrigger value="changed">Changed {changed.length}</TabsTrigger>
            <TabsTrigger value="all">All {diffs.length}</TabsTrigger>
          </TabsList>
        </Tabs>
      </CardHeader>
      <CardContent className="divide-y px-0">
        {shown.length === 0 && (
          <p className="p-6 text-center text-sm text-muted-foreground">
            No case changed between the two runs.
          </p>
        )}
        {shown.map((d) => {
          const detailed = d.change === "regressed" || d.change === "improved";
          return (
            <div key={d.case_id}>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3 text-sm">
                <span className="inline-flex items-center gap-1.5 font-mono text-xs">
                  {d.case_id}
                  {d.critical && <CriticalMark />}
                </span>
                <span className="text-muted-foreground">{d.label ?? "–"}</span>
                <ChangeLabel change={d.change} />
                {d.candidate_failed_metrics.length > 0 && (
                  <span className="text-xs text-muted-foreground">
                    now failing: {d.candidate_failed_metrics.join(", ")}
                  </span>
                )}
              </div>
              {detailed && <SideBySide diff={d} candidate={candidate} reference={reference} />}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

export function Compare() {
  const [params] = useSearchParams();
  const overview = useOverview();
  const runs = useRuns({ limit: 100 });
  const candidateId = params.get("candidate");
  const against = params.get("against");
  const baseline = against ? undefined : (params.get("baseline") ?? "main");

  const comparison = useCompare(
    candidateId ? { candidate: candidateId, against: against ?? undefined, baseline } : null,
  );
  const candidateRun = useRun(candidateId ?? undefined);
  const referenceRun = useRun(comparison.data?.baseline_run_id);

  const baselines = overview.data?.baselines.map((b) => b.name) ?? ["main"];

  return (
    <>
      <PageHeader
        title="Compare"
        description="Check any run against a baseline or another run. Nothing is saved."
      />
      <Pickers runs={runs.data?.items ?? []} baselines={baselines} />

      {!candidateId ? (
        <EmptyState icon={GitCompareArrows} title="Choose a run to check">
          Pick a run above. By default it is compared with baseline <code>main</code>, exactly as
          the CI gate does.
        </EmptyState>
      ) : comparison.isError ? (
        <ErrorState error={comparison.error} onRetry={comparison.refetch} />
      ) : comparison.isPending ? (
        <LoadingBlock className="h-96" />
      ) : (
        <div className={cn("grid gap-6", comparison.isPlaceholderData && "opacity-60")}>
          <VerdictHeader
            comparison={comparison.data}
            candidateLabel={
              <>
                Run <RunLink runId={comparison.data.candidate_run_id} />
              </>
            }
            referenceLabel={
              comparison.data.baseline_name ? (
                <>
                  baseline <b className="font-medium text-foreground">{comparison.data.baseline_name}</b>{" "}
                  (<RunLink runId={comparison.data.baseline_run_id} />)
                </>
              ) : (
                <>
                  run <RunLink runId={comparison.data.baseline_run_id} />
                </>
              )
            }
          />
          <ComparisonPanels comparison={comparison.data} />
          <CaseList
            diffs={comparison.data.cases}
            candidate={candidateRun.data}
            reference={referenceRun.data}
          />
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            Same result as the CLI: <code>regguard compare {candidateId}</code>
            <ArrowRight className="size-3" aria-hidden /> exit code 4 on FAIL.
          </p>
        </div>
      )}
    </>
  );
}

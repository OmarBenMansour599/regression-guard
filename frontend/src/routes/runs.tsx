import { ChevronLeft, ChevronRight, ListChecks } from "lucide-react";
import { useSearchParams } from "react-router";
import { useOverview, useRuns } from "@/api/queries";
import { CliHint, EmptyState, ErrorState, LoadingBlock, PageHeader } from "@/components/page";
import { RunsTable } from "@/components/runs-table";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export const PAGE_SIZE = 25;
const ALL = "all";

export function Runs() {
  const [params, setParams] = useSearchParams();
  const prompt = params.get("prompt") ?? ALL;
  const status = params.get("status") ?? ALL;
  const page = Math.max(1, Number(params.get("page") ?? "1") || 1);

  const overview = useOverview();
  const runs = useRuns({
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
    prompt_version: prompt === ALL ? undefined : prompt,
    status: status === ALL ? undefined : (status as "completed" | "error"),
  });

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value === ALL || (key === "page" && value === "1")) next.delete(key);
    else next.set(key, value);
    if (key !== "page") next.delete("page"); // a new filter starts on page 1
    setParams(next, { replace: key !== "page" });
  };

  const total = runs.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const filtered = prompt !== ALL || status !== ALL;

  return (
    <>
      <PageHeader
        title="Runs"
        description="Every evaluation recorded in the history database, newest first."
      />

      <div className="mb-4 flex flex-wrap items-center gap-2" role="group" aria-label="Filters">
        <Select value={prompt} onValueChange={(v) => update("prompt", v)}>
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
        <Select value={status} onValueChange={(v) => update("status", v)}>
          <SelectTrigger className="w-40" aria-label="Run status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Any status</SelectItem>
            <SelectItem value="completed">Completed</SelectItem>
            <SelectItem value="error">Error</SelectItem>
          </SelectContent>
        </Select>
        {filtered && (
          <Button variant="ghost" size="sm" onClick={() => setParams(new URLSearchParams())}>
            Clear filters
          </Button>
        )}
        <span className="ml-auto text-sm text-muted-foreground" aria-live="polite">
          {runs.data ? `${total} run${total === 1 ? "" : "s"}` : ""}
        </span>
      </div>

      {runs.isError ? (
        <ErrorState error={runs.error} onRetry={runs.refetch} />
      ) : runs.isPending ? (
        <LoadingBlock className="h-96" />
      ) : runs.data.items.length === 0 ? (
        filtered ? (
          <EmptyState icon={ListChecks} title="No run matches these filters" />
        ) : (
          <EmptyState icon={ListChecks} title="No runs recorded yet">
            <p className="mb-3">Import the runs saved on disk, or run an evaluation:</p>
            <CliHint command="uv run python -m regguard history import" />
          </EmptyState>
        )
      ) : (
        <Card className="gap-0 py-0">
          <CardContent className={runs.isPlaceholderData ? "px-2 opacity-60" : "px-2"}>
            <RunsTable runs={runs.data.items} detailed />
          </CardContent>
        </Card>
      )}

      {pages > 1 && (
        <nav className="mt-4 flex items-center justify-end gap-2" aria-label="Pages">
          <span className="mr-2 text-sm text-muted-foreground">
            Page {page} of {pages}
          </span>
          <Button
            variant="outline"
            size="icon"
            disabled={page <= 1}
            onClick={() => update("page", String(page - 1))}
            aria-label="Previous page"
          >
            <ChevronLeft aria-hidden />
          </Button>
          <Button
            variant="outline"
            size="icon"
            disabled={page >= pages}
            onClick={() => update("page", String(page + 1))}
            aria-label="Next page"
          >
            <ChevronRight aria-hidden />
          </Button>
        </nav>
      )}
    </>
  );
}

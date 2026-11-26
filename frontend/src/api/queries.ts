import { QueryClient, keepPreviousData, useQuery } from "@tanstack/react-query";
import { ApiError, api } from "./client";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000, // pages switch instantly from cache, then refresh quietly
        refetchOnWindowFocus: true,
        retry: (count, error) =>
          count < 2 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
      },
    },
  });
}

export const useHealth = () =>
  useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 60_000 });

export const useOverview = () => useQuery({ queryKey: ["overview"], queryFn: api.overview });

export const useRuns = (query: Parameters<typeof api.runs>[0] = {}) =>
  useQuery({
    queryKey: ["runs", query],
    queryFn: () => api.runs(query),
    placeholderData: keepPreviousData, // no flicker when filtering or paging
  });

export const useDrift = (baseline = "main") =>
  useQuery({ queryKey: ["drift", baseline], queryFn: () => api.drift({ baseline }) });

export const useRun = (runId: string | undefined) =>
  useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.run(runId as string),
    enabled: Boolean(runId),
    staleTime: Infinity, // a stored run never changes
  });

export const useCompare = (query: Parameters<typeof api.compare>[0] | null) =>
  useQuery({
    queryKey: ["compare", query],
    queryFn: () => api.compare(query as Parameters<typeof api.compare>[0]),
    enabled: query !== null && Boolean(query.candidate),
    placeholderData: keepPreviousData,
  });

export const useTrend = (metric: string, promptVersion?: string) =>
  useQuery({
    queryKey: ["trend", metric, promptVersion ?? ""],
    queryFn: () => api.trend({ metric, prompt_version: promptVersion, limit: 200 }),
    placeholderData: keepPreviousData,
  });

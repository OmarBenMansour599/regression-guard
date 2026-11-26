import type { DriftReport, Overview, RunPage, RunSummary } from "@/api/client";

export function runSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: "20261118T112155Z-edd66e",
    prompt_version: "v2",
    dataset_version: "v1",
    model: "google/gemma-4-26b-a4b-it:free",
    status: "completed",
    trigger: "manual",
    started_at: "2026-11-18T11:21:55Z",
    cases: 12,
    api_calls: 12,
    cache_hits: 0,
    metrics: { pass_rate: 2 / 3, schema_valid: 2 / 3 },
    verdict: "fail",
    verdict_baseline: "main",
    ...overrides,
  };
}

export const overview: Overview = {
  name: "support-email-classifier",
  app: "support_email_classifier",
  prompts: [
    { version: "v1", description: "", model: "m", content_hash: "sha256:aa", created_at: null },
    { version: "v2", description: "", model: "m", content_hash: "sha256:bb", created_at: null },
  ],
  dataset: {
    version: "v1",
    content_hash: "sha256:cc",
    cases: 24,
    critical: 2,
    labels: { billing: 6 },
    difficulty: { easy: 24 },
  },
  baselines: [
    {
      name: "main",
      source_run_id: "20261118T112032Z-a635b1",
      promoted_at: "2026-11-18T11:30:00Z",
      note: "",
      git_sha: null,
      prompt_version: "v1",
      prompt_hash: "sha256:1b01bf653477aaaa",
      model: "m",
      dataset_version: "v1",
      cases: 12,
      metrics: { pass_rate: 1 },
    },
  ],
  recorded_prompt_versions: ["v1", "v2"],
  notes: [],
};

export const drift: DriftReport = {
  app: "support-email-classifier",
  baseline_run_id: "20261118T112032Z-a635b1",
  baseline_name: "main",
  status: "insufficient",
  comparable_runs: 4,
  fresh_runs: 0,
  latest_run_id: null,
  metrics: [],
  notes: [],
  created_at: "2026-11-26T10:00:00Z",
};

export function runPage(items: RunSummary[]): RunPage {
  return { items, total: items.length, limit: 50, offset: 0 };
}

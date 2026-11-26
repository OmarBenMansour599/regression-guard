import type { Comparison, RunDetail, Schemas, TrendPoint } from "@/api/client";

type CaseResult = Schemas["CaseResult"];

function caseResult(caseId: string, overrides: Partial<CaseResult> = {}): CaseResult {
  return {
    case_id: caseId,
    sample_idx: 0,
    raw_output: '{"category": "billing", "summary": "Customer asks about a charge."}',
    parsed_output: { category: "billing", summary: "Customer asks about a charge." },
    scores: [{ name: "schema_valid", value: 1, passed: true, detail: {} }],
    passed: true,
    latency_ms: 1200,
    usage: { prompt_tokens: 380, completion_tokens: 30 },
    cached: false,
    error: null,
    judge: null,
    ...overrides,
  };
}

export const unreadable = caseResult("email-0012", {
  raw_output: '[{"category": "general", "summary": "Henry asks"}]',
  parsed_output: null,
  scores: [{ name: "schema_valid", value: 0, passed: false, detail: {} }],
  passed: false,
});

export function runDetail(overrides: Partial<RunDetail["run"]> = {}, inputs = true): RunDetail {
  const meta: RunDetail["run"]["meta"] = {
    run_id: "20261118T112155Z-edd66e",
    app: "support-email-classifier",
    prompt_version: "v2",
    prompt_hash: "sha256:f43fec97f798aaaa",
    dataset_version: "v1",
    dataset_hash: "sha256:35b18b00df81aaaa",
    provider: "openai_compatible",
    model: "google/gemma-4-26b-a4b-it:free",
    model_override: false,
    served_models: [],
    served_providers: ["Parasail"],
    params: {},
    selection: { ids: [], limit: 12, seed: 0, tags: [] },
    n_samples: 1,
    case_labels: { "email-0001": "billing", "email-0012": "general" },
    critical_case_ids: ["email-0001"],
    execution: {
      api_calls: 12,
      cache_hits: 0,
      retries: 0,
      cache_mode: "read-write",
      judge_api_calls: 0,
      judge_cache_hits: 0,
      judge_retries: 0,
      cost_usd: 0.00046,
      judge_cost_usd: 0,
    },
    judge: null,
    git_sha: "79f91f1dd306abcdef",
    trigger: "manual",
    started_at: "2026-11-18T11:21:55Z",
    finished_at: "2026-11-18T11:22:40Z",
    regguard_version: "0.1.0",
  };
  return {
    run: {
      meta,
      status: "completed",
      cases: [caseResult("email-0001"), unreadable],
      aggregates: {
        pass_rate: { value: 0.5, n: 2, ci_low: null, ci_high: null },
        schema_valid: { value: 0.5, n: 2, ci_low: null, ci_high: null },
      },
      error: null,
      ...overrides,
    },
    comparisons: [],
    inputs: inputs
      ? {
          "email-0001": { email: "I was charged twice <script>alert(1)</script>" },
          "email-0012": { email: "Partnership opportunity" },
        }
      : {},
    expected: inputs
      ? {
          "email-0001": { category: "billing", summary: "Double charge." },
          "email-0012": { category: "general", summary: "Partnership." },
        }
      : {},
    notes: inputs ? [] : ["Dataset v1 changed since this run: inputs are not shown."],
  };
}

export const comparison: Comparison = {
  app: "support-email-classifier",
  baseline_run_id: "20261118T112032Z-a635b1",
  baseline_name: "main",
  candidate_run_id: "20261118T112155Z-edd66e",
  verdict: "fail",
  reasons: [
    {
      code: "critical_regression",
      severity: "fail",
      metric: "schema_valid",
      message: "schema_valid 100.0% → 66.7% (-33.3 pts), 4 regressed / 0 improved of 12, p=0.062",
    },
    { code: "statistical_power", severity: "info", metric: null, message: "12 paired cases" },
  ],
  metrics: [
    {
      metric: "schema_valid",
      kind: "rate",
      baseline: 1,
      candidate: 2 / 3,
      delta: -1 / 3,
      unit: "absolute",
      n: 12,
      regressed: 4,
      improved: 0,
      p_value: 0.0625,
      level: "critical",
      gating: true,
    },
  ],
  cases: [
    {
      case_id: "email-0012",
      change: "regressed",
      label: "general",
      critical: false,
      baseline_failed_metrics: [],
      candidate_failed_metrics: ["schema_valid"],
    },
    {
      case_id: "email-0001",
      change: "still_pass",
      label: "billing",
      critical: true,
      baseline_failed_metrics: [],
      candidate_failed_metrics: [],
    },
  ],
  counts: { regressed: 1, still_pass: 1 },
  gate: {},
  created_at: "2026-11-26T10:00:00Z",
};

export function trendPoint(i: number, overrides: Partial<TrendPoint> = {}): TrendPoint {
  return {
    run_id: `run-${i}`,
    started_at: `2026-11-${10 + i}T10:00:00Z`,
    prompt_version: "v1",
    value: 1,
    n: 12,
    status: "completed",
    fresh: false,
    ...overrides,
  };
}

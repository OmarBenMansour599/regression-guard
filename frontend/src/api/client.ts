import type { components, operations } from "./schema";

/** API types, generated from the backend's OpenAPI description (`npm run gen:api`). */
export type Schemas = components["schemas"];
export type Health = Schemas["HealthInfo"];
export type Overview = Schemas["AppOverview"];
export type RunPage = Schemas["RunPage"];
export type RunSummary = Schemas["RunSummary"];
export type RunDetail = Schemas["RunDetail"];
export type Comparison = Schemas["Comparison"];
export type TrendPoint = Schemas["TrendPoint"];
export type DriftReport = Schemas["DriftReport"];
export type Verdict = Schemas["Verdict"];

type Query<Op extends keyof operations> = operations[Op] extends {
  parameters: { query?: infer Q };
}
  ? NonNullable<Q>
  : never;

/** An HTTP error from the API, with the server's explanation. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function get<T>(path: string, query?: Record<string, unknown>): Promise<T> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const url = params.size ? `${path}?${params}` : path;
  let response: Response;
  try {
    response = await fetch(url, { headers: { Accept: "application/json" } });
  } catch {
    throw new ApiError(0, "The RegressionGuard server is not reachable. Is `regguard serve` running?");
  }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* not JSON: keep the status */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => get<Health>("/api/health"),
  overview: () => get<Overview>("/api/overview"),
  runs: (query: Query<"listRuns"> = {}) => get<RunPage>("/api/runs", query),
  run: (runId: string) => get<RunDetail>(`/api/runs/${encodeURIComponent(runId)}`),
  compare: (query: Query<"compareRuns">) => get<Comparison>("/api/compare", query),
  trend: (query: Query<"getTrend">) => get<TrendPoint[]>("/api/trends", query),
  drift: (query: Query<"getDrift"> = {}) => get<DriftReport>("/api/drift", query),
};

"""Shared, immutable data types. Single source of truth for result files, DB, API and UI.

A *run* has a status (did it execute?). Only a *comparison* has a verdict
(is it safe relative to a baseline?). The same run can pass against one baseline
and fail against another.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RunStatus(StrEnum):
    COMPLETED = "completed"
    ERROR = "error"  # infrastructure failure; never a quality regression


class Verdict(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    ERROR = "error"  # candidate run had an infrastructure failure: not comparable


class Trigger(StrEnum):
    MANUAL = "manual"
    CI = "ci"
    SCHEDULE = "schedule"


class Usage(FrozenModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class Completion(FrozenModel):
    text: str
    usage: Usage
    latency_ms: float = Field(ge=0)
    model: str
    cached: bool = False


class MetricScore(FrozenModel):
    name: str
    value: float
    passed: bool | None = None  # None for purely informational metrics
    detail: dict[str, Any] = Field(default_factory=dict)


class CaseError(FrozenModel):
    type: str  # e.g. "timeout", "rate_limit", "invalid_json"
    message: str
    retryable: bool = False


class CaseResult(FrozenModel):
    case_id: str
    sample_idx: int = Field(default=0, ge=0)
    raw_output: str | None = None
    parsed_output: dict[str, Any] | None = None
    scores: list[MetricScore] = Field(default_factory=list)
    passed: bool
    latency_ms: float | None = None
    usage: Usage | None = None
    cached: bool = False
    error: CaseError | None = None


class AggregateScore(FrozenModel):
    value: float
    n: int = Field(ge=0)
    ci_low: float | None = None
    ci_high: float | None = None


class CaseSelection(FrozenModel):
    """Which golden cases a run used (empty = all)."""

    limit: int | None = None
    ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    seed: int = 0


class ExecutionStats(FrozenModel):
    cache_mode: str = "off"
    cache_hits: int = 0
    api_calls: int = 0  # real provider calls, including retries
    retries: int = 0


class RunMeta(FrozenModel):
    run_id: str
    app: str
    prompt_version: str
    prompt_hash: str
    dataset_version: str
    dataset_hash: str
    provider: str
    model: str  # model actually requested (prompt's model, or the override)
    model_override: bool = False  # True if REGGUARD_LLM_MODEL replaced the prompt's model
    served_models: tuple[str, ...] = ()  # model ids reported back by the provider
    params: dict[str, Any] = Field(default_factory=dict)
    selection: CaseSelection = Field(default_factory=CaseSelection)
    n_samples: int = Field(default=1, ge=1)
    case_labels: dict[str, str] = Field(default_factory=dict)  # case id -> golden label (slices)
    critical_case_ids: tuple[str, ...] = ()  # golden cases marked `critical: true`
    execution: ExecutionStats = Field(default_factory=ExecutionStats)
    judge: dict[str, Any] | None = None
    git_sha: str | None = None
    trigger: Trigger = Trigger.MANUAL
    started_at: datetime
    finished_at: datetime | None = None
    regguard_version: str


class RunResult(FrozenModel):
    meta: RunMeta
    status: RunStatus
    cases: list[CaseResult]
    aggregates: dict[str, AggregateScore] = Field(default_factory=dict)
    error: str | None = None


# --- baselines and comparisons --------------------------------------------------------------


class BaselineHeader(FrozenModel):
    name: str
    app: str
    source_run_id: str
    promoted_at: datetime
    git_sha: str | None = None  # repository state when the baseline was promoted
    note: str = ""
    regguard_version: str


class BaselineFile(FrozenModel):
    """A pinned, committed snapshot of a trusted run: ``<baselines_dir>/<name>.json``."""

    header: BaselineHeader
    run: RunResult


class CaseChange(StrEnum):
    REGRESSED = "regressed"  # passed in baseline, fails in candidate
    IMPROVED = "improved"  # failed in baseline, passes in candidate
    STILL_PASS = "still_pass"
    STILL_FAIL = "still_fail"
    NEW = "new"  # only in candidate
    REMOVED = "removed"  # only in baseline
    SKIPPED = "skipped"  # infra error in either run: excluded from pairing


class CaseDiff(FrozenModel):
    case_id: str
    change: CaseChange
    label: str | None = None
    critical: bool = False
    baseline_failed_metrics: tuple[str, ...] = ()
    candidate_failed_metrics: tuple[str, ...] = ()


class Severity(StrEnum):
    INFO = "info"
    WARN = "warn"
    FAIL = "fail"


class Reason(FrozenModel):
    """Machine-readable reason for a verdict: ``code`` is stable, ``message`` is for people."""

    code: str
    severity: Severity
    message: str
    metric: str | None = None


class ThresholdLevel(StrEnum):
    OK = "ok"
    WARN = "warn"
    CRITICAL = "critical"


class MetricDelta(FrozenModel):
    metric: str
    baseline: float
    candidate: float
    delta: float | None  # in `unit`; None when relative and baseline is 0
    unit: str  # "absolute" or "relative"
    n: int  # paired cases (binary metrics) or candidate sample size (others)
    regressed: int | None = None  # paired pass->fail flips (binary metrics only)
    improved: int | None = None
    p_value: float | None = None  # one-sided exact McNemar (binary metrics only)
    level: ThresholdLevel = ThresholdLevel.OK
    gating: bool = False


class Comparison(FrozenModel):
    app: str
    baseline_run_id: str
    baseline_name: str | None = None  # None when comparing directly against a run
    candidate_run_id: str
    verdict: Verdict
    reasons: list[Reason] = Field(default_factory=list)
    metrics: list[MetricDelta] = Field(default_factory=list)
    cases: list[CaseDiff] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)  # CaseChange value -> count
    gate: dict[str, Any] = Field(default_factory=dict)  # the gate config used (reproducibility)
    created_at: datetime

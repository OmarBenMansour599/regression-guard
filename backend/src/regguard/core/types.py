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

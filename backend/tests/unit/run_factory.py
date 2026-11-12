"""Build small, fully controlled RunResults for comparison tests (no provider, no dataset)."""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

from regguard.core.types import (
    AggregateScore,
    CaseError,
    CaseResult,
    MetricScore,
    RunMeta,
    RunResult,
    RunStatus,
    Usage,
)

CATEGORIES = ("billing", "technical", "account", "general")

# Outcome codes: "pass", "label" (wrong category), "schema" (invalid output), "error" (infra).


def make_case(case_id: str, outcome: str, *, sample_idx: int = 0, tokens: int = 100) -> CaseResult:
    if outcome == "error":
        return CaseResult(
            case_id=case_id,
            sample_idx=sample_idx,
            passed=False,
            error=CaseError(type="timeout", message="timed out", retryable=True),
        )
    schema_ok = outcome != "schema"
    label_ok = outcome == "pass"
    return CaseResult(
        case_id=case_id,
        sample_idx=sample_idx,
        raw_output="{}",
        parsed_output={"category": "billing"} if schema_ok else None,
        scores=[
            MetricScore(name="schema_valid", value=float(schema_ok), passed=schema_ok),
            MetricScore(name="label_exact", value=float(label_ok), passed=label_ok),
        ],
        passed=schema_ok and label_ok,
        latency_ms=1000.0,
        usage=Usage(prompt_tokens=tokens - 20, completion_tokens=20),
    )


def outcomes(n: int, *, fail: Iterable[int] = (), code: str = "label") -> dict[str, str]:
    """``n`` cases ``email-0001..``; the 1-based indices in ``fail`` get outcome ``code``."""
    failing = set(fail)
    return {f"email-{i:04d}": (code if i in failing else "pass") for i in range(1, n + 1)}


def make_run(
    cases: Mapping[str, str],
    *,
    run_id: str = "20261112T000000Z-aaaaaa",
    app: str = "t",
    prompt_version: str = "v1",
    dataset_hash: str = "sha256:" + "a" * 64,
    status: RunStatus = RunStatus.COMPLETED,
    critical: Iterable[str] = (),
    tokens: int = 100,
    latency_p95: float | None = 1000.0,
    labels: Mapping[str, str] | None = None,
) -> RunResult:
    results = [make_case(cid, outcome, tokens=tokens) for cid, outcome in cases.items()]
    ok = [r for r in results if r.error is None]
    schema = [float(r.parsed_output is not None) for r in ok]
    aggregates = {
        "error_rate": AggregateScore(
            value=(len(results) - len(ok)) / len(results) if results else 0.0, n=len(results)
        ),
        "schema_valid": AggregateScore(
            value=sum(schema) / len(schema) if schema else 0.0, n=len(ok)
        ),
    }
    if latency_p95 is not None:
        aggregates["latency_ms_p95"] = AggregateScore(value=latency_p95, n=len(ok))
    case_labels = (
        dict(labels)
        if labels is not None
        else {cid: CATEGORIES[i % len(CATEGORIES)] for i, cid in enumerate(cases)}
    )
    meta = RunMeta(
        run_id=run_id,
        app=app,
        prompt_version=prompt_version,
        prompt_hash="sha256:" + "b" * 64,
        dataset_version="v1",
        dataset_hash=dataset_hash,
        provider="mock",
        model="mock-model",
        case_labels=case_labels,
        critical_case_ids=tuple(critical),
        started_at=datetime(2026, 11, 12, tzinfo=UTC),
        regguard_version="0.0.0",
    )
    return RunResult(
        meta=meta,
        status=status,
        cases=results,
        aggregates=aggregates,
        error="aborted" if status is RunStatus.ERROR else None,
    )

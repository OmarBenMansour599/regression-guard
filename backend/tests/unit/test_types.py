from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from regguard.core.types import (
    AggregateScore,
    CaseResult,
    MetricScore,
    RunMeta,
    RunResult,
    RunStatus,
    Usage,
    Verdict,
)


def _meta() -> RunMeta:
    return RunMeta(
        run_id="run-1",
        app="support-email-classifier",
        prompt_version="v1",
        prompt_hash="abc",
        dataset_version="v1",
        dataset_hash="def",
        provider="groq",
        model="m",
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        regguard_version="0.1.0",
    )


def _result() -> RunResult:
    case = CaseResult(
        case_id="c1",
        raw_output='{"category": "billing"}',
        parsed_output={"category": "billing"},
        scores=[MetricScore(name="category_exact", value=1.0, passed=True)],
        passed=True,
        latency_ms=120.0,
        usage=Usage(prompt_tokens=100, completion_tokens=20),
    )
    return RunResult(
        meta=_meta(),
        status=RunStatus.COMPLETED,
        cases=[case],
        aggregates={"category_exact": AggregateScore(value=1.0, n=1)},
    )


def test_run_result_json_round_trip() -> None:
    original = _result()
    restored = RunResult.model_validate_json(original.model_dump_json())
    assert restored == original


def test_models_are_immutable() -> None:
    with pytest.raises(ValidationError):
        _result().cases[0].passed = False  # type: ignore[misc]


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Usage.model_validate({"prompt_tokens": 1, "completion_tokens": 1, "oops": 2})


def test_negative_tokens_rejected() -> None:
    with pytest.raises(ValidationError):
        Usage(prompt_tokens=-1, completion_tokens=0)


def test_total_tokens() -> None:
    assert Usage(prompt_tokens=7, completion_tokens=3).total_tokens == 10


def test_verdict_is_separate_from_run_status() -> None:
    # ERROR = candidate run failed (infra): not comparable, never a quality FAIL.
    assert {v.value for v in Verdict} == {"pass", "warn", "fail", "error"}
    assert {s.value for s in RunStatus} == {"completed", "error"}

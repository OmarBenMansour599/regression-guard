import random
from pathlib import Path

import pytest

from regguard.apps.support_email import SPEC
from regguard.core.errors import ProviderError
from regguard.core.types import CaseSelection, RunStatus
from regguard.datasets.models import Dataset, DatasetManifest, Difficulty, GoldenCase
from regguard.evaluation.cache import CacheMode, ResponseCache
from regguard.evaluation.executor import Executor, RateLimiter, RetryPolicy
from regguard.evaluation.runner import RunPlan, execute_run
from regguard.metrics.aggregate import percentile
from regguard.metrics.registry import default_metrics
from regguard.prompts.loader import load_prompt_version
from regguard.providers.base import CompletionRequest
from regguard.providers.mock_provider import MockProvider
from tests.conftest import EXAMPLE_APP
from tests.unit.test_executor import FakeTime

PROMPT = load_prompt_version(EXAMPLE_APP / "prompts" / "classify", "v1")


def _case(case_id: str, category: str, marker: str) -> GoldenCase:
    return GoldenCase(
        id=case_id,
        input={"email": f"[{marker}] some email text"},
        expected={"category": category, "summary": "Customer writes."},
        difficulty=Difficulty.EASY,
    )


CASES = (
    _case("c1", "billing", "correct-billing"),
    _case("c2", "technical", "correct-technical"),
    _case("c3", "account", "wrong-label"),
    _case("c4", "general", "invalid-json"),
    _case("c5", "general", "provider-down"),
)
DATASET = Dataset(manifest=DatasetManifest(name="emails", version="v1"), cases=CASES)


def responder(request: CompletionRequest) -> str | Exception:
    text = request.messages[-1].content
    if "correct-billing" in text:
        return '{"category": "billing", "summary": "Customer asks about a charge."}'
    if "correct-technical" in text:
        return '{"category": "technical", "summary": "Customer reports a bug in the app."}'
    if "wrong-label" in text:
        return '{"category": "billing", "summary": "Customer asks something about the account."}'
    if "invalid-json" in text:
        return "Sorry, I cannot help with that."
    return ProviderError("down", retryable=False, status_code=400)


def _plan(cases: tuple[GoldenCase, ...] = CASES, **kw: object) -> RunPlan:
    return RunPlan(
        app_name="support-email-classifier",
        spec=SPEC,
        prompt=PROMPT,
        dataset=DATASET,
        cases=cases,
        metrics=default_metrics(SPEC),
        selection=CaseSelection(),
        **kw,  # type: ignore[arg-type]
    )


def _executor(tmp_path: Path, provider: MockProvider) -> Executor:
    t = FakeTime()
    return Executor(
        provider,
        cache=ResponseCache(tmp_path, CacheMode.READ_WRITE, namespace="t"),
        limiter=RateLimiter(6000, clock=t.clock, sleep=t.sleep),
        policy=RetryPolicy(max_retries=0),
        sleep=t.sleep,
        rng=random.Random(0),
    )


async def _run(tmp_path: Path, plan: RunPlan, max_error_rate: float = 0.5):  # type: ignore[no-untyped-def]
    return await execute_run(
        plan,
        _executor(tmp_path, MockProvider(responder)),
        run_id="r1",
        provider_name="mock",
        cache_mode="read-write",
        max_error_rate=max_error_rate,
    )


def _outage_run(tmp_path: Path, provider: MockProvider):  # type: ignore[no-untyped-def]
    t = FakeTime()
    executor = Executor(
        provider,
        cache=ResponseCache(tmp_path, CacheMode.READ_WRITE, namespace="t"),
        limiter=RateLimiter(6000, clock=t.clock, sleep=t.sleep),
        concurrency=1,
        policy=RetryPolicy(max_retries=4, outage_after_failures=3, second_pass_delay_s=60.0),
        sleep=t.sleep,
        rng=random.Random(0),
    )
    plan = _plan(cases=CASES[:2])
    run = execute_run(
        plan, executor, run_id="r1", provider_name="mock", cache_mode="rw", max_error_rate=0.1
    )
    return run, t


def _down_for(n: int) -> MockProvider:
    """The first ``n`` calls get HTTP 503, then the provider recovers."""
    calls = [0]

    def answer(request: CompletionRequest) -> str | Exception:
        calls[0] += 1
        return (
            ProviderError("overloaded", retryable=True, status_code=503)
            if calls[0] <= n
            else (responder(request))
        )

    return MockProvider(answer)


async def test_second_pass_recovers_from_a_short_outage(tmp_path: Path) -> None:
    provider = _down_for(3)  # trips the switch on case 1; case 2 is not even sent
    run, time = _outage_run(tmp_path, provider)
    result = await run
    assert result.status is RunStatus.COMPLETED
    assert all(c.error is None for c in result.cases)
    assert 60.0 in time.sleeps
    assert len(provider.calls) == 5  # 3 failed + 2 in the second pass


async def test_long_outage_still_ends_in_error_without_burning_calls(tmp_path: Path) -> None:
    provider = _down_for(1000)
    run, _ = _outage_run(tmp_path, provider)
    result = await run
    assert result.status is RunStatus.ERROR
    assert {c.error.type for c in result.cases if c.error} == {"unavailable"}
    assert len(provider.calls) == 6  # 3 per pass, instead of 5 attempts x 2 cases x 2 passes


async def test_case_outcomes(tmp_path: Path) -> None:
    result = await _run(tmp_path, _plan())
    by_id = {c.case_id: c for c in result.cases}
    assert by_id["c1"].passed
    assert by_id["c2"].passed
    assert not by_id["c3"].passed
    assert by_id["c3"].parsed_output == {
        "category": "billing",
        "summary": "Customer asks something about the account.",
    }
    assert not by_id["c4"].passed
    assert by_id["c4"].parsed_output is None
    assert by_id["c4"].raw_output == "Sorry, I cannot help with that."
    # Invalid output: only schema_valid applies; label/summary metrics are not applicable.
    assert [s.name for s in by_id["c4"].scores] == ["schema_valid"]
    assert {s.name for s in by_id["c1"].scores} == {
        "schema_valid",
        "label_exact",
        "summary_format",
        "summary_similarity",
    }
    assert by_id["c5"].error is not None
    assert by_id["c5"].scores == []


async def test_aggregates_exclude_errored_cases(tmp_path: Path) -> None:
    agg = (await _run(tmp_path, _plan())).aggregates
    assert agg["error_rate"].value == 0.2
    assert agg["pass_rate"].n == 4  # c5 errored: excluded from quality
    assert agg["pass_rate"].value == 0.5
    assert agg["schema_valid"].value == 0.75
    assert agg["label_exact"].n == 3  # c4 (invalid JSON) is not a classification error
    assert agg["label_exact"].value == pytest.approx(2 / 3)
    assert agg["label_exact/billing"].value == 1.0
    assert agg["label_exact/account"].value == 0.0
    assert "label_exact/general" not in agg  # c4 invalid, c5 errored
    assert agg["precision/billing"].value == 0.5  # c1 correct, c3 predicted billing wrongly
    assert agg["f1/technical"].value == 1.0
    assert agg["macro_f1"].value == pytest.approx((2 / 3 + 1.0 + 0.0) / 3)
    assert agg["summary_format"].value == 1.0
    assert 0.0 <= agg["summary_similarity"].value <= 1.0
    assert "latency_ms_p50" in agg
    assert agg["tokens_total"].value > 0


async def test_status_error_when_error_rate_too_high(tmp_path: Path) -> None:
    result = await _run(tmp_path, _plan(), max_error_rate=0.1)
    assert result.status is RunStatus.ERROR
    assert result.error is not None
    assert "error rate" in result.error


async def test_status_completed_within_error_budget(tmp_path: Path) -> None:
    result = await _run(tmp_path, _plan(), max_error_rate=0.5)
    assert result.status is RunStatus.COMPLETED


async def test_metadata_provenance(tmp_path: Path) -> None:
    meta = (await _run(tmp_path, _plan(model_override="other/model"))).meta
    assert meta.model == "other/model"
    assert meta.model_override is True
    assert meta.served_models == ("other/model",)
    assert meta.prompt_hash == PROMPT.content_hash
    assert meta.dataset_hash == DATASET.content_hash
    assert meta.params["temperature"] == 0.0
    assert meta.execution.api_calls == 5


async def test_samples_produce_one_result_each(tmp_path: Path) -> None:
    result = await _run(tmp_path, _plan(cases=CASES[:2], n_samples=3))
    assert len(result.cases) == 6
    assert sorted({c.sample_idx for c in result.cases}) == [0, 1, 2]


async def test_rerun_is_fully_cached_and_latency_excludes_cache(tmp_path: Path) -> None:
    provider = MockProvider(responder)
    plan = _plan(cases=CASES[:2])
    kwargs = {"run_id": "r", "provider_name": "mock", "cache_mode": "rw", "max_error_rate": 0.5}
    await execute_run(plan, _executor(tmp_path, provider), **kwargs)  # type: ignore[arg-type]
    second = await execute_run(plan, _executor(tmp_path, provider), **kwargs)  # type: ignore[arg-type]
    assert second.meta.execution.api_calls == 0
    assert second.meta.execution.cache_hits == 2
    assert all(c.cached for c in second.cases)
    assert "latency_ms_p50" not in second.aggregates


def test_percentile_nearest_rank() -> None:
    values = [10.0, 20.0, 30.0, 40.0]
    assert percentile(values, 50) == 20.0
    assert percentile(values, 95) == 40.0
    assert percentile([5.0], 95) == 5.0

"""Run a prepared set of golden cases through the executor and score them into a RunResult."""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from regguard import __version__
from regguard.apps.base import AppSpec, parse_output
from regguard.core.errors import DataValidationError
from regguard.core.types import (
    CaseResult,
    CaseSelection,
    ExecutionStats,
    JudgeResult,
    RunMeta,
    RunResult,
    RunStatus,
    Trigger,
)
from regguard.datasets.models import Dataset, GoldenCase
from regguard.evaluation.executor import Executor
from regguard.evaluation.judge import JudgeScorer
from regguard.metrics.aggregate import compute_aggregates
from regguard.metrics.base import Metric, ScoringInput
from regguard.metrics.judge import JudgeOutput, judge_metric_score
from regguard.prompts.models import PromptConfig
from regguard.prompts.render import build_request

ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class RunPlan:
    app_name: str
    spec: AppSpec
    prompt: PromptConfig
    dataset: Dataset
    cases: tuple[GoldenCase, ...]
    metrics: Sequence[Metric]
    selection: CaseSelection
    n_samples: int = 1
    model_override: str | None = None

    @property
    def total_calls(self) -> int:
        return len(self.cases) * self.n_samples

    @property
    def model(self) -> str:
        return self.model_override or self.prompt.model.model


async def _run_case(
    plan: RunPlan,
    executor: Executor,
    case: GoldenCase,
    sample_idx: int,
    judge: JudgeScorer | None = None,
) -> CaseResult:
    request = build_request(plan.prompt, case.input, model_override=plan.model_override)
    outcome = await executor.call(request, sample_idx=sample_idx)
    if outcome.completion is None:
        return CaseResult(case_id=case.id, sample_idx=sample_idx, passed=False, error=outcome.error)

    completion = outcome.completion
    output: dict[str, object] | None
    parse_error: str | None = None
    try:
        output = parse_output(completion.text, plan.spec).model_dump(mode="json")
    except DataValidationError as exc:
        output, parse_error = None, str(exc)

    item = ScoringInput(case=case, output=output, parse_error=parse_error)
    scores = [s for m in plan.metrics if (s := m.score(item)) is not None]
    gating = {m.name for m in plan.metrics if m.gating}
    passed = all(s.passed for s in scores if s.name in gating and s.passed is not None)

    judged: JudgeResult | None = None
    if judge is not None and output is not None:
        judged = await judge.score(case, output, sample_idx=sample_idx)
        if judged is not None and judged.score is not None:
            scores.append(judge_metric_score(JudgeOutput(score=judged.score, reason=judged.reason)))
    return CaseResult(
        judge=judged,
        case_id=case.id,
        sample_idx=sample_idx,
        raw_output=completion.text,
        parsed_output=output,
        scores=scores,
        passed=passed,
        latency_ms=completion.latency_ms,
        usage=completion.usage,
        cached=completion.cached,
    )


def _case_labels(plan: RunPlan) -> dict[str, str]:
    field = plan.spec.label_field
    if field is None:
        return {}
    return {c.id: str(c.expected[field]) for c in plan.cases if field in c.expected}


async def execute_run(
    plan: RunPlan,
    executor: Executor,
    *,
    run_id: str,
    provider_name: str,
    cache_mode: str,
    max_error_rate: float,
    git_sha: str | None = None,
    trigger: Trigger = Trigger.MANUAL,
    on_progress: ProgressCallback | None = None,
    judge: JudgeScorer | None = None,
) -> RunResult:
    started_at = datetime.now(UTC)
    total = plan.total_calls
    done = 0

    async def tracked(case: GoldenCase, sample_idx: int) -> CaseResult:
        nonlocal done
        result = await _run_case(plan, executor, case, sample_idx, judge)
        done += 1
        if on_progress is not None:
            on_progress(done, total)
        return result

    jobs = [(case, s) for case in plan.cases for s in range(plan.n_samples)]
    results = list(await asyncio.gather(*(tracked(case, s) for case, s in jobs)))

    # Second pass: cases that failed for temporary reasons (overload, outage switch) get one
    # more chance after a pause. Still failing -> they count as errors, as before.
    retry = [i for i, r in enumerate(results) if r.error is not None and r.error.retryable]
    if retry and executor.second_pass_enabled and executor.aborted_reason is None:
        await executor.start_second_pass(len(retry))
        again = await asyncio.gather(*(_run_case(plan, executor, *jobs[i], judge) for i in retry))
        for i, result in zip(retry, again, strict=True):
            results[i] = result

    aggregates = compute_aggregates(results, plan.cases, label_field=plan.spec.label_field)
    error_rate = aggregates["error_rate"].value

    status, error = RunStatus.COMPLETED, None
    if executor.aborted_reason is not None:
        status, error = RunStatus.ERROR, f"aborted: {executor.aborted_reason}"
    elif error_rate > max_error_rate:
        status = RunStatus.ERROR
        error = f"error rate {error_rate:.0%} exceeds the {max_error_rate:.0%} limit"
    elif judge is not None and judge.executor.aborted_reason is not None:
        status, error = RunStatus.ERROR, f"judge aborted: {judge.executor.aborted_reason}"
    elif (judge_errors := aggregates.get("judge_error_rate")) is not None and (
        judge_errors.value > max_error_rate
    ):
        status = RunStatus.ERROR
        error = f"judge error rate {judge_errors.value:.0%} exceeds the {max_error_rate:.0%} limit"

    meta = RunMeta(
        run_id=run_id,
        app=plan.app_name,
        prompt_version=plan.prompt.version,
        prompt_hash=plan.prompt.content_hash,
        dataset_version=plan.dataset.manifest.version,
        dataset_hash=plan.dataset.content_hash,
        provider=provider_name,
        model=plan.model,
        model_override=plan.model_override is not None,
        served_models=tuple(sorted(executor.served_models)),
        served_providers=tuple(sorted(executor.served_providers)),
        params=plan.prompt.model.model_dump(mode="json", exclude={"model"}),
        selection=plan.selection,
        n_samples=plan.n_samples,
        case_labels=_case_labels(plan),
        critical_case_ids=tuple(c.id for c in plan.cases if c.critical),
        execution=ExecutionStats(
            cache_mode=cache_mode,
            cache_hits=executor.cache_hits,
            api_calls=executor.api_calls,
            retries=executor.retries,
            judge_cache_hits=judge.executor.cache_hits if judge else 0,
            judge_api_calls=judge.executor.api_calls if judge else 0,
            judge_retries=judge.executor.retries if judge else 0,
            cost_usd=round(executor.cost_usd, 8),
            judge_cost_usd=round(judge.executor.cost_usd, 8) if judge else 0.0,
        ),
        judge=judge.describe() if judge else None,
        git_sha=git_sha,
        trigger=trigger,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        regguard_version=__version__,
    )
    return RunResult(
        meta=meta, status=status, cases=list(results), aggregates=aggregates, error=error
    )

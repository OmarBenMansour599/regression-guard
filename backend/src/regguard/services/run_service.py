"""Evaluation run use case: prepare (validate + budget estimate), then execute and save."""

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from regguard.apps.base import AppSpec, parse_output
from regguard.apps.config import AppConfig
from regguard.apps.registry import get_app
from regguard.core.config import Settings
from regguard.core.errors import ConfigError, DataValidationError, RegGuardError
from regguard.core.types import CaseSelection, RunResult, Trigger
from regguard.datasets.select import select_cases
from regguard.evaluation.cache import CacheMode, ResponseCache
from regguard.evaluation.executor import Executor, RateLimiter, RetryPolicy
from regguard.evaluation.judge import JudgeScorer, judge_request
from regguard.evaluation.runner import ProgressCallback, RunPlan, execute_run
from regguard.metrics.judge import CANDIDATE_VAR, REFERENCE_VAR
from regguard.metrics.registry import default_metrics
from regguard.prompts.loader import load_prompt_version
from regguard.prompts.models import PromptConfig
from regguard.prompts.render import build_request
from regguard.providers.base import CompletionRequest, LLMProvider
from regguard.services.datasets import load_app_dataset
from regguard.services.invoke import ensure_compatible
from regguard.storage.file_store import new_run_id, save_run

MOCK_JUDGE_RESPONSE = '{"reason": "Mock judge: offline run.", "score": 4}'


class BudgetExceededError(RegGuardError):
    def __init__(self, needed: int, limit: int) -> None:
        super().__init__(
            f"This run needs {needed} API call(s), above the limit of {limit}. "
            f"Use --limit to run fewer cases, --no-judge to skip the judge, "
            f"or raise --max-requests."
        )
        self.needed = needed
        self.limit = limit


@dataclass(frozen=True)
class RunOptions:
    prompt_version: str
    dataset_version: str | None = None
    limit: int | None = None
    ids: Sequence[str] = ()
    tags: Sequence[str] = ()
    seed: int = 0
    n_samples: int = 1
    cache_mode: CacheMode = CacheMode.READ_WRITE
    max_requests: int = 50
    trigger: Trigger = Trigger.MANUAL
    judge: bool = True  # False: skip the LLM judge even if regguard.yaml configures one


@dataclass(frozen=True)
class PreparedRun:
    plan: RunPlan
    cache: ResponseCache
    uncached_calls: int  # app calls + judge calls that are not in the cache
    options: RunOptions = field(repr=False)
    judge_prompt: PromptConfig | None = None
    judge_calls: int = 0  # planned judge calls (at most one per app call)
    uncached_judge_calls: int = 0


def _cache_namespace(provider_name: str, settings: Settings) -> str:
    return f"{provider_name}:{settings.llm_base_url}"


def load_judge_prompt(config: AppConfig, spec: AppSpec) -> PromptConfig | None:
    """The app's judge prompt, or None when no judge is configured or enabled."""
    judge = config.judge
    if judge is None or not judge.enabled:
        return None
    if spec.summary_field is None:
        raise ConfigError(f"App '{spec.name}' has no summary field for a judge to grade")
    prompt = load_prompt_version(judge.prompts_dir, judge.version)
    expected = {*spec.input_variables, REFERENCE_VAR, CANDIDATE_VAR}
    if set(prompt.input_variables) != expected:
        raise ConfigError(
            f"Judge prompt {prompt.id}@{prompt.version} must use exactly the variables "
            f"{sorted(expected)}, got {sorted(prompt.input_variables)}"
        )
    return prompt


def mock_responder(
    spec: AppSpec, judge_prompt: PromptConfig | None
) -> Callable[[CompletionRequest], str | Exception]:
    """Offline answers for the mock provider: the app's example output, or a judge verdict."""
    judge_model = judge_prompt.model.model if judge_prompt else None

    def respond(request: CompletionRequest) -> str | Exception:
        if judge_model is not None and request.model == judge_model:
            return MOCK_JUDGE_RESPONSE
        return spec.mock_response

    return respond


def _judge_estimate(
    plan: RunPlan,
    judge_prompt: PromptConfig,
    cache: ResponseCache,
    app_requests: Sequence[tuple[CompletionRequest, int, int]],
) -> tuple[int, int]:
    """(planned, uncached) judge calls. An app output we do not have yet is assumed to
    need one judge call; a cached invalid output needs none (nothing to judge)."""
    summary_field = plan.spec.summary_field or ""
    planned = uncached = 0
    for request, case_idx, sample_idx in app_requests:
        completion = cache.get(cache.key(request, sample_idx))
        if completion is None:
            planned, uncached = planned + 1, uncached + 1
            continue
        try:
            output = parse_output(completion.text, plan.spec).model_dump(mode="json")
        except DataValidationError:
            continue
        judge_req = judge_request(judge_prompt, plan.cases[case_idx], output, summary_field)
        if judge_req is None:
            continue
        planned += 1
        if not cache.contains(cache.key(judge_req, sample_idx)):
            uncached += 1
    return planned, uncached


def prepare_run(
    config: AppConfig, options: RunOptions, settings: Settings, *, provider_name: str
) -> PreparedRun:
    """Load and validate everything, and estimate API calls. Makes no API calls."""
    spec = get_app(config.app)
    prompt = load_prompt_version(config.prompts_dir, options.prompt_version)
    ensure_compatible(spec, prompt)
    dataset = load_app_dataset(config, spec, options.dataset_version)
    cases = select_cases(
        dataset.cases,
        ids=options.ids or None,
        tags=options.tags or None,
        limit=options.limit,
        label_field=spec.label_field,
        seed=options.seed,
    )
    if not cases:
        raise DataValidationError(
            f"No cases match the selection (tags={list(options.tags)}, ids={list(options.ids)}); "
            "refusing to run an empty evaluation"
        )
    plan = RunPlan(
        app_name=config.name,
        spec=spec,
        prompt=prompt,
        dataset=dataset,
        cases=cases,
        metrics=default_metrics(spec),
        selection=CaseSelection(
            limit=options.limit, ids=tuple(options.ids), tags=tuple(options.tags), seed=options.seed
        ),
        n_samples=options.n_samples,
        model_override=settings.llm_model,
    )
    cache = ResponseCache(
        settings.cache_dir, options.cache_mode, namespace=_cache_namespace(provider_name, settings)
    )
    app_requests = [
        (build_request(prompt, case.input, model_override=settings.llm_model), i, s)
        for i, case in enumerate(cases)
        for s in range(options.n_samples)
    ]
    uncached = sum(1 for req, _, s in app_requests if not cache.contains(cache.key(req, s)))
    judge_prompt = load_judge_prompt(config, spec) if options.judge else None
    judge_calls = uncached_judge = 0
    if judge_prompt is not None:
        judge_calls, uncached_judge = _judge_estimate(plan, judge_prompt, cache, app_requests)
    return PreparedRun(
        plan=plan,
        cache=cache,
        uncached_calls=uncached + uncached_judge,
        options=options,
        judge_prompt=judge_prompt,
        judge_calls=judge_calls,
        uncached_judge_calls=uncached_judge,
    )


def check_budget(prepared: PreparedRun) -> None:
    if prepared.uncached_calls > prepared.options.max_requests:
        raise BudgetExceededError(prepared.uncached_calls, prepared.options.max_requests)


def git_sha(cwd: Path) -> str | None:
    """Current commit, suffixed ``-dirty`` if there are uncommitted changes."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607 - git from PATH is intended
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],  # noqa: S607
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return f"{sha}-dirty" if dirty else sha


async def execute_prepared(
    prepared: PreparedRun,
    provider: LLMProvider,
    settings: Settings,
    *,
    git_revision: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> RunResult:
    """Run (budget must already be checked), save the result, and return it."""
    # One limiter for both executors: app and judge calls share the same API key and quota.
    limiter = RateLimiter(settings.requests_per_minute)
    policy = RetryPolicy(max_retries=settings.max_retries)
    executor = Executor(
        provider,
        cache=prepared.cache,
        limiter=limiter,
        concurrency=settings.max_concurrency,
        policy=policy,
    )
    judge: JudgeScorer | None = None
    summary_field = prepared.plan.spec.summary_field
    if prepared.judge_prompt is not None and summary_field is not None:
        judge_executor = Executor(
            provider,
            cache=prepared.cache,
            limiter=limiter,
            concurrency=settings.max_concurrency,
            policy=policy,
        )
        judge = JudgeScorer(prepared.judge_prompt, judge_executor, summary_field)
    try:
        result = await execute_run(
            prepared.plan,
            executor,
            run_id=new_run_id(),
            provider_name=provider.name,
            cache_mode=prepared.cache.mode.value,
            max_error_rate=settings.max_error_rate,
            git_sha=git_revision,
            trigger=prepared.options.trigger,
            on_progress=on_progress,
            judge=judge,
        )
    finally:
        await provider.aclose()
    save_run(settings.runs_dir, result)
    return result

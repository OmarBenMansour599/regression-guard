"""Evaluation run use case: prepare (validate + budget estimate), then execute and save."""

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from regguard.apps.config import AppConfig
from regguard.apps.registry import get_app
from regguard.core.config import Settings
from regguard.core.errors import DataValidationError, RegGuardError
from regguard.core.types import CaseSelection, RunResult, Trigger
from regguard.datasets.select import select_cases
from regguard.evaluation.cache import CacheMode, ResponseCache
from regguard.evaluation.executor import Executor, RateLimiter, RetryPolicy
from regguard.evaluation.runner import ProgressCallback, RunPlan, execute_run
from regguard.metrics.registry import default_metrics
from regguard.prompts.loader import load_prompt_version
from regguard.prompts.render import build_request
from regguard.providers.base import LLMProvider
from regguard.services.datasets import load_app_dataset
from regguard.services.invoke import ensure_compatible
from regguard.storage.file_store import new_run_id, save_run


class BudgetExceededError(RegGuardError):
    def __init__(self, needed: int, limit: int) -> None:
        super().__init__(
            f"This run needs {needed} API call(s), above the limit of {limit}. "
            f"Use --limit to run fewer cases, or raise --max-requests."
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


@dataclass(frozen=True)
class PreparedRun:
    plan: RunPlan
    cache: ResponseCache
    uncached_calls: int
    options: RunOptions = field(repr=False)


def _cache_namespace(provider_name: str, settings: Settings) -> str:
    return f"{provider_name}:{settings.llm_base_url}"


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
    uncached = sum(
        1
        for case in cases
        for s in range(options.n_samples)
        if not cache.contains(
            cache.key(build_request(prompt, case.input, model_override=settings.llm_model), s)
        )
    )
    return PreparedRun(plan=plan, cache=cache, uncached_calls=uncached, options=options)


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
    executor = Executor(
        provider,
        cache=prepared.cache,
        limiter=RateLimiter(settings.requests_per_minute),
        concurrency=settings.max_concurrency,
        policy=RetryPolicy(max_retries=settings.max_retries),
    )
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
        )
    finally:
        await provider.aclose()
    save_run(settings.runs_dir, result)
    return result

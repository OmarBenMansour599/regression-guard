"""Calls the provider for many requests: concurrency, rate limit, retries, cache, early abort.

This is the ONLY place with retry policy (providers make exactly one attempt).
Clock, sleep and RNG are injectable so tests run instantly and deterministically.
"""

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from regguard.core.errors import ProviderError
from regguard.core.logging import get_logger
from regguard.core.types import CaseError, Completion
from regguard.evaluation.cache import ResponseCache
from regguard.providers.base import CompletionRequest, LLMProvider

_log = get_logger(__name__)

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]

_AUTH_STATUSES = {401, 403}
_MAX_RETRY_AFTER_S = 120.0


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 4
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0
    # 429s without Retry-After (e.g. a throttled shared upstream pool) last much longer than
    # transport glitches: wait longer, with a guaranteed minimum (equal jitter).
    rate_limit_base_delay_s: float = 5.0
    rate_limit_max_delay_s: float = 60.0
    # 5xx from an overloaded upstream also need a real pause (equal jitter, 2 s base).
    server_error_base_delay_s: float = 2.0
    abort_after_consecutive_failures: int = 5
    # Outage switch: after this many failed attempts in a row (any call: 5xx, 429, network),
    # the provider counts as down. Retries stop and new calls are not sent, so a burst of
    # upstream errors cannot eat the call budget. None = off.
    outage_after_failures: int | None = None
    # Pause before the runner's second pass over cases that failed for temporary reasons.
    # Upstream overloads often last about a minute. None = no second pass.
    second_pass_delay_s: float | None = None


@dataclass(frozen=True)
class CallOutcome:
    completion: Completion | None
    error: CaseError | None
    attempts: int


class CallBudget:
    """Hard cap on real provider calls for a whole run, retries included.

    One instance is shared by every executor of a run (app and judge), because they spend
    the same API key's quota. Cache hits are free and never spend from it.
    """

    def __init__(self, limit: int) -> None:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        self.limit = limit
        self.spent = 0

    def try_spend(self) -> bool:
        if self.spent >= self.limit:
            return False
        self.spent += 1
        return True


class RateLimiter:
    """Spaces request starts evenly: at most ``per_minute`` starts per 60 s."""

    def __init__(
        self, per_minute: int, *, clock: Clock = time.monotonic, sleep: Sleep = asyncio.sleep
    ) -> None:
        self._interval = 60.0 / per_minute
        self._clock = clock
        self._sleep = sleep
        self._next_start: float | None = None
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = self._clock()
            if self._next_start is not None and self._next_start > now:
                await self._sleep(self._next_start - now)
                now = self._next_start
            self._next_start = now + self._interval


def _error_type(exc: ProviderError) -> str:
    status = exc.status_code
    if status == 429:
        return "rate_limit"
    if status in _AUTH_STATUSES:
        return "auth"
    if status is not None and status >= 500:
        return "server_error"
    if status is not None and status >= 400:
        return "client_error"
    return "transport_error"


class Executor:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        cache: ResponseCache,
        limiter: RateLimiter,
        concurrency: int = 3,
        policy: RetryPolicy | None = None,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
        budget: CallBudget | None = None,
    ) -> None:
        self._provider = provider
        self._budget = budget
        self._cache = cache
        self._limiter = limiter
        self._semaphore = asyncio.Semaphore(concurrency)
        self._policy = policy or RetryPolicy()
        self._sleep = sleep
        self._rng = rng or random.Random()  # noqa: S311 - jitter, not security
        self._consecutive_failures = 0
        self._failed_attempts_streak = 0
        self._unavailable: ProviderError | None = None  # set while the outage switch is on
        self.aborted_reason: str | None = None
        self.cache_hits = 0
        self.api_calls = 0
        self.retries = 0
        self.served_models: set[str] = set()  # model ids the provider says it used
        self.served_providers: set[str] = set()  # upstream providers that answered
        self.cost_usd = 0.0  # fresh calls only: cache hits were paid for by an earlier run

    def _backoff(self, attempt: int, *, status: int | None) -> float:
        """Transport glitches: full jitter in [0, ceiling].
        Rate limits and server errors: equal jitter in [ceiling/2, ceiling], so we never
        retry almost instantly against a struggling upstream.
        """
        p = self._policy
        factor = float(1 << attempt)  # 2**attempt as an exact int, attempt >= 0
        if status == 429:
            ceiling = min(p.rate_limit_max_delay_s, p.rate_limit_base_delay_s * factor)
            return ceiling / 2 + self._rng.uniform(0, ceiling / 2)
        if status is not None and status >= 500:
            ceiling = min(p.max_delay_s, p.server_error_base_delay_s * factor)
            return ceiling / 2 + self._rng.uniform(0, ceiling / 2)
        ceiling = min(p.max_delay_s, p.base_delay_s * factor)
        return self._rng.uniform(0, ceiling)

    def _abort(self, reason: str) -> None:
        if self.aborted_reason is None:
            self.aborted_reason = reason
            _log.error("run_aborted", reason=reason)

    def _aborted_outcome(self, attempts: int) -> CallOutcome:
        message = f"run aborted: {self.aborted_reason}"
        return CallOutcome(None, CaseError(type="aborted", message=message), attempts)

    def _unavailable_outcome(self, attempts: int) -> CallOutcome:
        """Not completed because the provider is down: retryable in the second pass."""
        message = (
            f"not completed: provider unavailable after {self._failed_attempts_streak} failed "
            f"attempts in a row (last: {self._unavailable})"
        )
        error = CaseError(type="unavailable", message=message, retryable=True)
        return CallOutcome(None, error, attempts)

    def _note_failed_attempt(self, exc: ProviderError) -> None:
        self._failed_attempts_streak += 1
        threshold = self._policy.outage_after_failures
        if (
            threshold is not None
            and self._unavailable is None
            and self._failed_attempts_streak >= threshold
        ):
            self._unavailable = exc
            _log.warning(
                "provider_unavailable",
                failed_attempts=self._failed_attempts_streak,
                error=_error_type(exc),
            )

    @property
    def second_pass_enabled(self) -> bool:
        return self._policy.second_pass_delay_s is not None

    async def start_second_pass(self, cases: int) -> None:
        """Pause, then let calls through again (the runner retries the failed cases once)."""
        delay = self._policy.second_pass_delay_s or 0.0
        _log.info("second_pass", cases=cases, wait_s=delay)
        await self._sleep(delay)
        self._unavailable = None
        self._failed_attempts_streak = 0
        self._consecutive_failures = 0

    def _failure(self, exc: ProviderError, attempts: int) -> CallOutcome:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._policy.abort_after_consecutive_failures:
            self._abort(f"{self._consecutive_failures} consecutive failed calls (last: {exc})")
        error = CaseError(type=_error_type(exc), message=str(exc), retryable=exc.retryable)
        return CallOutcome(None, error, attempts)

    async def call(self, request: CompletionRequest, *, sample_idx: int = 0) -> CallOutcome:
        key = self._cache.key(request, sample_idx)
        cached = self._cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            self.served_models.add(cached.model)
            if cached.served_by:
                self.served_providers.add(cached.served_by)
            return CallOutcome(cached, None, 0)

        async with self._semaphore:
            attempt = 0
            while True:
                if self.aborted_reason is not None:
                    return self._aborted_outcome(attempt)
                if self._unavailable is not None:  # provider down: do not spend calls
                    return self._unavailable_outcome(attempt)
                if self._budget is not None and not self._budget.try_spend():
                    self._abort(
                        f"API call budget exhausted ({self._budget.limit} calls, "
                        "retries included); raise --max-requests or retry later"
                    )
                    return self._aborted_outcome(attempt)
                await self._limiter.acquire()
                self.api_calls += 1
                try:
                    completion = await self._provider.complete(request)
                except ProviderError as exc:
                    attempt += 1
                    if exc.status_code in _AUTH_STATUSES:
                        self._abort(f"authentication failed: {exc}")
                        return self._failure(exc, attempt)
                    if exc.fatal:  # every other call would fail the same way
                        self._abort(str(exc))
                        return self._failure(exc, attempt)
                    if not exc.retryable:
                        return self._failure(exc, attempt)
                    self._note_failed_attempt(exc)
                    if self._unavailable is not None:
                        return self._unavailable_outcome(attempt)
                    if attempt > self._policy.max_retries:
                        return self._failure(exc, attempt)
                    delay = (
                        min(exc.retry_after_s, _MAX_RETRY_AFTER_S)
                        if exc.retry_after_s is not None
                        else self._backoff(attempt - 1, status=exc.status_code)
                    )
                    self.retries += 1
                    # Short line only: the full message is kept on the case if it finally fails.
                    _log.info(
                        "provider_retry",
                        attempt=attempt,
                        error=_error_type(exc),
                        wait_s=round(delay, 1),
                    )
                    await self._sleep(delay)
                    continue
                self._consecutive_failures = 0
                self._failed_attempts_streak = 0
                self.served_models.add(completion.model)
                if completion.served_by:
                    self.served_providers.add(completion.served_by)
                self.cost_usd += completion.cost_usd or 0.0
                self._cache.put(key, completion)
                return CallOutcome(completion, None, attempt + 1)

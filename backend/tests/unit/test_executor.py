import random
from collections.abc import Iterator
from pathlib import Path

import pytest

from regguard.core.errors import ProviderError
from regguard.core.types import Completion, Usage
from regguard.evaluation.cache import CacheMode, ResponseCache
from regguard.evaluation.executor import CallBudget, Executor, RateLimiter, RetryPolicy
from regguard.providers.base import CompletionRequest, Message
from regguard.providers.mock_provider import MockProvider

REQUEST = CompletionRequest(model="m", messages=(Message(role="user", content="hi"),))


class FakeTime:
    """Fake clock + sleep: sleeping advances the clock instantly and is recorded."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def scripted(*steps: str | Exception) -> MockProvider:
    """Provider returning/raising the given steps in order (last step repeats)."""
    it: Iterator[str | Exception] = iter(steps)
    last: list[str | Exception] = [steps[-1]]

    def responder(_: CompletionRequest) -> str | Exception:
        last[0] = next(it, last[0])
        return last[0]

    return MockProvider(responder)


def make_executor(
    provider: MockProvider,
    tmp_path: Path,
    *,
    mode: CacheMode = CacheMode.OFF,
    time: FakeTime | None = None,
    policy: RetryPolicy | None = None,
    per_minute: int = 6000,
) -> tuple[Executor, FakeTime]:
    t = time or FakeTime()
    executor = Executor(
        provider,
        cache=ResponseCache(tmp_path / "cache", mode, namespace="test"),
        limiter=RateLimiter(per_minute, clock=t.clock, sleep=t.sleep),
        policy=policy or RetryPolicy(max_retries=3),
        sleep=t.sleep,
        rng=random.Random(0),
    )
    return executor, t


def retryable(status: int = 503, retry_after: float | None = None) -> ProviderError:
    return ProviderError("boom", retryable=True, status_code=status, retry_after_s=retry_after)


async def test_success_first_try(tmp_path: Path) -> None:
    executor, _ = make_executor(scripted("ok"), tmp_path)
    outcome = await executor.call(REQUEST)
    assert outcome.completion is not None
    assert outcome.completion.text == "ok"
    assert outcome.attempts == 1
    assert executor.api_calls == 1
    assert executor.served_models == {"m"}


async def test_retries_then_succeeds(tmp_path: Path) -> None:
    executor, t = make_executor(scripted(retryable(), retryable(), "ok"), tmp_path)
    outcome = await executor.call(REQUEST)
    assert outcome.completion is not None
    assert outcome.attempts == 3
    assert executor.retries == 2
    # 503s: equal jitter on a 2 s base -> [1, 2] then [2, 4]
    for delay, (low, high) in zip(t.sleeps, [(1, 2), (2, 4)], strict=True):
        assert low <= delay <= high


async def test_transport_errors_use_short_full_jitter(tmp_path: Path) -> None:
    glitch = ProviderError("reset", retryable=True, status_code=None)
    executor, t = make_executor(scripted(glitch, glitch, "ok"), tmp_path)
    await executor.call(REQUEST)
    assert len(t.sleeps) == 2
    assert all(0 <= d <= 2.0 for d in t.sleeps)  # full jitter within 1 s, 2 s ceilings


async def test_rate_limit_backoff_is_long_with_minimum(tmp_path: Path) -> None:
    provider = scripted(retryable(429), retryable(429), retryable(429), retryable(429), "ok")
    executor, t = make_executor(provider, tmp_path, policy=RetryPolicy(max_retries=4))
    outcome = await executor.call(REQUEST)
    assert outcome.completion is not None
    # equal jitter on 5s base, 60s cap: [2.5,5], [5,10], [10,20], [20,40]
    for delay, (low, high) in zip(t.sleeps, [(2.5, 5), (5, 10), (10, 20), (20, 40)], strict=True):
        assert low <= delay <= high


async def test_call_budget_caps_retries_and_aborts(tmp_path: Path) -> None:
    budget = CallBudget(3)
    provider = scripted(retryable())  # always 503
    executor, _ = make_executor(provider, tmp_path, policy=RetryPolicy(max_retries=10))
    executor._budget = budget
    outcome = await executor.call(REQUEST)
    assert outcome.completion is None
    assert executor.api_calls == 3  # not 11: the budget stopped the retries
    assert budget.spent == 3
    assert executor.aborted_reason is not None
    assert "budget exhausted (3 calls" in executor.aborted_reason
    assert outcome.error is not None
    assert outcome.error.type == "aborted"


async def test_call_budget_is_shared_and_cache_hits_are_free(tmp_path: Path) -> None:
    budget = CallBudget(2)
    first, _ = make_executor(scripted("ok"), tmp_path, mode=CacheMode.READ_WRITE)
    second, _ = make_executor(scripted("ok"), tmp_path, mode=CacheMode.READ_WRITE)
    first._budget = second._budget = budget
    await first.call(REQUEST)  # spends 1
    await first.call(REQUEST)  # cache hit: free
    other = CompletionRequest(model="m", messages=(Message(role="user", content="other"),))
    await second.call(other)  # spends the 2nd
    third = CompletionRequest(model="m", messages=(Message(role="user", content="third"),))
    outcome = await second.call(third)
    assert budget.spent == 2
    assert outcome.completion is None
    assert second.aborted_reason is not None


def test_call_budget_rejects_negative_limit() -> None:
    with pytest.raises(ValueError, match=">= 0"):
        CallBudget(-1)


async def test_retry_after_is_honored(tmp_path: Path) -> None:
    executor, t = make_executor(scripted(retryable(429, retry_after=7.0), "ok"), tmp_path)
    await executor.call(REQUEST)
    assert t.sleeps == [7.0]


async def test_gives_up_after_max_retries(tmp_path: Path) -> None:
    executor, _ = make_executor(scripted(retryable(429)), tmp_path)
    outcome = await executor.call(REQUEST)
    assert outcome.completion is None
    assert outcome.error is not None
    assert outcome.error.type == "rate_limit"
    assert outcome.attempts == 4  # 1 + 3 retries
    assert executor.api_calls == 4


async def test_non_retryable_fails_fast(tmp_path: Path) -> None:
    provider = scripted(ProviderError("bad", retryable=False, status_code=400))
    executor, t = make_executor(provider, tmp_path)
    outcome = await executor.call(REQUEST)
    assert outcome.error is not None
    assert outcome.error.type == "client_error"
    assert outcome.attempts == 1
    assert t.sleeps == []


async def test_auth_error_aborts_whole_run(tmp_path: Path) -> None:
    provider = scripted(ProviderError("no key", retryable=False, status_code=401))
    executor, _ = make_executor(provider, tmp_path)
    first = await executor.call(REQUEST)
    second = await executor.call(REQUEST)
    assert first.error is not None
    assert first.error.type == "auth"
    assert executor.aborted_reason is not None
    assert second.error is not None
    assert second.error.type == "aborted"
    assert len(provider.calls) == 1  # no further calls after abort


async def test_cost_counts_fresh_calls_only_and_providers_are_tracked(tmp_path: Path) -> None:
    paid = Completion(
        text="ok",
        usage=Usage(prompt_tokens=10, completion_tokens=2),
        latency_ms=5.0,
        model="m",
        served_by="PrimeIntellect",
        cost_usd=0.0001,
    )

    class Paid(MockProvider):
        async def complete(self, request: CompletionRequest) -> Completion:
            self.calls.append(request)
            return paid

    provider = Paid(lambda _: "unused")
    first, _ = make_executor(provider, tmp_path, mode=CacheMode.READ_WRITE)
    await first.call(REQUEST)
    assert first.cost_usd == pytest.approx(0.0001)
    assert first.served_providers == {"PrimeIntellect"}

    second, _ = make_executor(provider, tmp_path, mode=CacheMode.READ_WRITE)
    outcome = await second.call(REQUEST)  # same request: answered from the cache
    assert outcome.completion is not None and outcome.completion.cached
    assert second.cost_usd == 0.0  # paid for by the first run
    assert second.served_providers == {"PrimeIntellect"}  # still says who answered
    assert len(provider.calls) == 1


OUTAGE = RetryPolicy(max_retries=4, outage_after_failures=3, second_pass_delay_s=60.0)


async def test_outage_switch_stops_spending_calls(tmp_path: Path) -> None:
    """Real case 2026-11-24: 27 of 30 calls were 5xx; retrying burned the whole budget."""
    provider = scripted(retryable(503))
    executor, _ = make_executor(provider, tmp_path, policy=OUTAGE)
    first = await executor.call(REQUEST)  # 3 failed attempts, then the switch trips
    second = await executor.call(REQUEST)  # not even sent
    assert len(provider.calls) == 3
    assert first.error is not None and first.error.type == "unavailable"
    assert first.error.retryable and "3 failed attempts in a row" in first.error.message
    assert second.error is not None and second.error.type == "unavailable"
    assert executor.aborted_reason is None  # deferred, not aborted: a second pass can follow


async def test_success_resets_the_outage_streak(tmp_path: Path) -> None:
    provider = scripted(retryable(503), retryable(503), "ok", retryable(503), retryable(503), "ok")
    executor, _ = make_executor(provider, tmp_path, policy=OUTAGE)
    assert (await executor.call(REQUEST)).completion is not None
    assert (await executor.call(REQUEST)).completion is not None  # streak restarted at 0
    assert len(provider.calls) == 6


async def test_non_retryable_errors_do_not_trip_the_switch(tmp_path: Path) -> None:
    provider = scripted(ProviderError("bad request", status_code=400))
    executor, _ = make_executor(provider, tmp_path, policy=OUTAGE)
    for _ in range(4):
        outcome = await executor.call(REQUEST)
        assert outcome.error is not None and outcome.error.type == "client_error"
    assert len(provider.calls) == 4


async def test_second_pass_waits_and_lets_calls_through(tmp_path: Path) -> None:
    provider = scripted(retryable(503), retryable(503), retryable(503), "ok")
    executor, time = make_executor(provider, tmp_path, policy=OUTAGE)
    assert (await executor.call(REQUEST)).error is not None
    assert executor.second_pass_enabled
    await executor.start_second_pass(cases=1)
    assert time.sleeps[-1] == 60.0
    assert (await executor.call(REQUEST)).completion is not None


async def test_fatal_error_aborts_after_one_call(tmp_path: Path) -> None:
    """A key that cannot be sent fails every call: stop at once instead of burning the budget."""
    provider = scripted(ProviderError("bad header", fatal=True))
    executor, _ = make_executor(provider, tmp_path)
    first = await executor.call(REQUEST)
    second = await executor.call(REQUEST)
    assert first.error is not None and first.error.message == "bad header"
    assert executor.aborted_reason == "bad header"
    assert second.error is not None and second.error.type == "aborted"
    assert len(provider.calls) == 1


async def test_consecutive_failures_abort(tmp_path: Path) -> None:
    provider = scripted(ProviderError("bad", retryable=False, status_code=400))
    policy = RetryPolicy(max_retries=0, abort_after_consecutive_failures=3)
    executor, _ = make_executor(provider, tmp_path, policy=policy)
    for _ in range(4):
        await executor.call(REQUEST)
    assert executor.aborted_reason is not None
    assert "3 consecutive" in executor.aborted_reason
    assert len(provider.calls) == 3


async def test_success_resets_failure_streak(tmp_path: Path) -> None:
    bad = ProviderError("bad", retryable=False, status_code=400)
    provider = scripted(bad, bad, "ok", bad, bad)
    policy = RetryPolicy(max_retries=0, abort_after_consecutive_failures=3)
    executor, _ = make_executor(provider, tmp_path, policy=policy)
    for _ in range(5):
        await executor.call(REQUEST)
    assert executor.aborted_reason is None


async def test_rate_limiter_spaces_requests() -> None:
    t = FakeTime()
    limiter = RateLimiter(60, clock=t.clock, sleep=t.sleep)  # one start per second
    for _ in range(3):
        await limiter.acquire()
    assert t.sleeps == [1.0, 1.0]


@pytest.mark.parametrize(
    ("mode", "second_call_hits_provider", "hits"),
    [
        (CacheMode.READ_WRITE, False, 1),
        (CacheMode.REFRESH, True, 0),
        (CacheMode.OFF, True, 0),
    ],
)
async def test_cache_modes(
    tmp_path: Path, mode: CacheMode, second_call_hits_provider: bool, hits: int
) -> None:
    provider = scripted("ok")
    executor, _ = make_executor(provider, tmp_path, mode=mode)
    await executor.call(REQUEST)
    second = await executor.call(REQUEST)
    assert len(provider.calls) == (2 if second_call_hits_provider else 1)
    assert executor.cache_hits == hits
    assert second.completion is not None
    assert second.completion.cached is (hits == 1)


async def test_cache_key_depends_on_sample_and_namespace(tmp_path: Path) -> None:
    a = ResponseCache(tmp_path, CacheMode.READ_WRITE, namespace="p1")
    b = ResponseCache(tmp_path, CacheMode.READ_WRITE, namespace="p2")
    assert a.key(REQUEST, 0) != a.key(REQUEST, 1)
    assert a.key(REQUEST, 0) != b.key(REQUEST, 0)


async def test_refresh_writes_for_later_reuse(tmp_path: Path) -> None:
    provider = scripted("fresh")
    refresh, _ = make_executor(provider, tmp_path, mode=CacheMode.REFRESH)
    await refresh.call(REQUEST)
    reuse, _ = make_executor(provider, tmp_path, mode=CacheMode.READ_WRITE)
    outcome = await reuse.call(REQUEST)
    assert outcome.completion is not None
    assert outcome.completion.cached
    assert len(provider.calls) == 1


async def test_corrupt_cache_entry_is_a_miss(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path, CacheMode.READ_WRITE, namespace="t")
    key = cache.key(REQUEST)
    path = tmp_path / key[:2] / f"{key}.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert cache.get(key) is None

"""Deterministic, offline provider for tests and demos."""

from collections.abc import Callable

from regguard.core.types import Completion, Usage
from regguard.providers.base import CompletionRequest

# Returns the completion text, or an exception to raise (e.g. a ProviderError).
Responder = Callable[[CompletionRequest], str | Exception]


class MockProvider:
    name = "mock"

    def __init__(
        self,
        responder: Responder | str = '{"mock": true}',
        *,
        latency_ms: float = 1.0,
    ) -> None:
        self._responder = responder
        self._latency_ms = latency_ms
        self.calls: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest) -> Completion:
        self.calls.append(request)
        result = self._responder if isinstance(self._responder, str) else self._responder(request)
        if isinstance(result, Exception):
            raise result
        prompt_tokens = sum(len(m.content.split()) for m in request.messages)
        return Completion(
            text=result,
            usage=Usage(prompt_tokens=prompt_tokens, completion_tokens=len(result.split())),
            latency_ms=self._latency_ms,
            model=request.model,
        )

    async def aclose(self) -> None:
        return None

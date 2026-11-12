"""Provider-independent LLM interface.

A provider makes exactly ONE attempt per call. Retries, backoff and concurrency are the
executor's job (single place for policy, no stacked retries, honest latency numbers).
Providers report whether a retry could help via ``ProviderError.retryable``.
"""

from typing import Any, Literal, Protocol

from pydantic import Field

from regguard.core.types import Completion, FrozenModel


class Message(FrozenModel):
    role: Literal["system", "user", "assistant"]
    content: str


class CompletionRequest(FrozenModel):
    model: str
    messages: tuple[Message, ...]
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)
    seed: int | None = None
    json_mode: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)  # provider-specific passthrough


class LLMProvider(Protocol):
    name: str

    async def complete(self, request: CompletionRequest) -> Completion: ...

    async def aclose(self) -> None: ...

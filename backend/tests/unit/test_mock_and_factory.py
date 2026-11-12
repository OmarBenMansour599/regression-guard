import pytest
from pydantic import SecretStr

from regguard.core.config import Settings
from regguard.core.errors import ConfigError, ProviderError
from regguard.providers.base import CompletionRequest, Message
from regguard.providers.factory import build_provider
from regguard.providers.mock_provider import MockProvider
from regguard.providers.openai_compatible import OpenAICompatibleProvider


def _req(text: str = "hello world") -> CompletionRequest:
    return CompletionRequest(model="m", messages=(Message(role="user", content=text),))


async def test_mock_returns_fixed_text_and_records_calls() -> None:
    mock = MockProvider("ok")
    completion = await mock.complete(_req())
    assert completion.text == "ok"
    assert completion.usage.prompt_tokens == 2
    assert completion.model == "m"
    assert len(mock.calls) == 1


async def test_mock_responder_can_raise() -> None:
    mock = MockProvider(lambda r: ProviderError("boom", retryable=True))
    with pytest.raises(ProviderError, match="boom"):
        await mock.complete(_req())


async def test_mock_responder_sees_request() -> None:
    mock = MockProvider(lambda r: r.messages[-1].content.upper())
    assert (await mock.complete(_req("abc"))).text == "ABC"


def test_factory_builds_mock() -> None:
    provider = build_provider(Settings(llm_provider="mock"), mock_response="x")
    assert isinstance(provider, MockProvider)


def test_factory_requires_api_key() -> None:
    with pytest.raises(ConfigError, match="REGGUARD_LLM_API_KEY"):
        build_provider(Settings(llm_provider="openai_compatible", llm_api_key=None))


async def test_factory_builds_openai_compatible() -> None:
    provider = build_provider(Settings(llm_api_key=SecretStr("k")))
    assert isinstance(provider, OpenAICompatibleProvider)
    await provider.aclose()

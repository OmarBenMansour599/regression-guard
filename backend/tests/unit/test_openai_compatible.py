import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from regguard.core.errors import ProviderError
from regguard.providers.base import CompletionRequest, Message
from regguard.providers.openai_compatible import OpenAICompatibleProvider

BASE_URL = "https://llm.test/api/v1"
Handler = Callable[[httpx.Request], httpx.Response]


def _provider(handler: Handler) -> OpenAICompatibleProvider:
    client = httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    return OpenAICompatibleProvider(base_url=BASE_URL, api_key=SecretStr("k-123"), client=client)


def _request(**overrides: Any) -> CompletionRequest:
    fields: dict[str, Any] = {
        "model": "test/model",
        "messages": (Message(role="system", content="s"), Message(role="user", content="u")),
    }
    fields.update(overrides)
    return CompletionRequest(**fields)


def _ok(content: str = '{"a": 1}', usage: dict[str, int] | None = None) -> httpx.Response:
    body: dict[str, Any] = {
        "model": "test/model-2026",
        "choices": [{"message": {"role": "assistant", "content": content}}],
    }
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


async def test_success_parses_text_usage_and_model() -> None:
    provider = _provider(lambda r: _ok(usage={"prompt_tokens": 12, "completion_tokens": 5}))
    completion = await provider.complete(_request())
    assert completion.text == '{"a": 1}'
    assert completion.usage.prompt_tokens == 12
    assert completion.usage.completion_tokens == 5
    assert completion.model == "test/model-2026"
    assert completion.latency_ms >= 0


async def test_request_payload_and_headers() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return _ok(usage={"prompt_tokens": 1, "completion_tokens": 1})

    await _provider(handler).complete(
        _request(json_mode=True, seed=7, max_tokens=50, extra={"top_p": 0.9})
    )
    assert seen["url"] == f"{BASE_URL}/chat/completions"
    assert seen["auth"] == "Bearer k-123"
    body = seen["body"]
    assert body["model"] == "test/model"
    assert body["response_format"] == {"type": "json_object"}
    assert body["seed"] == 7
    assert body["max_tokens"] == 50
    assert body["top_p"] == 0.9
    assert body["messages"][0] == {"role": "system", "content": "s"}


async def test_json_mode_off_sends_no_response_format() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return _ok()

    await _provider(handler).complete(_request())
    assert "response_format" not in seen
    assert "seed" not in seen


async def test_rate_limit_is_retryable_with_retry_after() -> None:
    provider = _provider(
        lambda r: httpx.Response(429, headers={"retry-after": "3"}, text="slow down")
    )
    with pytest.raises(ProviderError) as info:
        await provider.complete(_request())
    assert info.value.retryable is True
    assert info.value.status_code == 429
    assert info.value.retry_after_s == 3.0


async def test_server_error_is_retryable() -> None:
    provider = _provider(lambda r: httpx.Response(503, text="unavailable"))
    with pytest.raises(ProviderError) as info:
        await provider.complete(_request())
    assert info.value.retryable is True


@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_client_errors_are_not_retryable(status: int) -> None:
    provider = _provider(lambda r: httpx.Response(status, text="nope"))
    with pytest.raises(ProviderError) as info:
        await provider.complete(_request())
    assert info.value.retryable is False
    assert info.value.status_code == status


async def test_timeout_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(ProviderError, match="timed out") as info:
        await _provider(handler).complete(_request())
    assert info.value.retryable is True


async def test_non_json_body() -> None:
    provider = _provider(lambda r: httpx.Response(200, text="<html>oops</html>"))
    with pytest.raises(ProviderError, match="not JSON"):
        await provider.complete(_request())


async def test_error_object_in_200_response() -> None:
    provider = _provider(
        lambda r: httpx.Response(200, json={"error": {"code": 502, "message": "upstream down"}})
    )
    with pytest.raises(ProviderError, match="upstream down") as info:
        await provider.complete(_request())
    assert info.value.retryable is True
    assert info.value.status_code == 502


async def test_malformed_choices() -> None:
    provider = _provider(lambda r: httpx.Response(200, json={"choices": []}))
    with pytest.raises(ProviderError, match="malformed"):
        await provider.complete(_request())


async def test_empty_content() -> None:
    provider = _provider(lambda r: _ok(content="   "))
    with pytest.raises(ProviderError, match="empty"):
        await provider.complete(_request())


async def test_missing_usage_defaults_to_zero() -> None:
    completion = await _provider(lambda r: _ok()).complete(_request())
    assert completion.usage.total_tokens == 0


async def test_upstream_error_message_is_readable() -> None:
    body = {
        "error": {
            "message": "Provider returned error",
            "code": 429,
            "metadata": {"raw": "model:free is temporarily rate-limited upstream."},
        }
    }
    provider = _provider(lambda r: httpx.Response(429, json=body))
    with pytest.raises(ProviderError) as info:
        await provider.complete(_request())
    assert str(info.value) == (
        "HTTP 429: Provider returned error: model:free is temporarily rate-limited upstream."
    )


async def test_api_key_not_in_error_messages() -> None:
    provider = _provider(lambda r: httpx.Response(401, text="invalid key"))
    with pytest.raises(ProviderError) as info:
        await provider.complete(_request())
    assert "k-123" not in str(info.value)


async def test_unsendable_header_is_fatal_and_never_quotes_the_key() -> None:
    """httpx quotes the bad header (with the key) in its message: found in a real CI run."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.LocalProtocolError("Illegal header value b'Bearer k-123\\n'")

    with pytest.raises(ProviderError) as info:
        await _provider(handler).complete(_request())
    assert info.value.fatal and not info.value.retryable
    assert "k-123" not in str(info.value)
    assert "spaces or line breaks" in str(info.value)


async def test_transport_error_text_is_redacted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("failed while sending Bearer k-123")

    with pytest.raises(ProviderError) as info:
        await _provider(handler).complete(_request())
    assert info.value.retryable and not info.value.fatal
    assert str(info.value) == "transport error: failed while sending Bearer ***"

"""Provider for any OpenAI-compatible Chat Completions endpoint (OpenRouter, Groq, ...)."""

import time
from typing import Any

import httpx
from pydantic import SecretStr

from regguard.core.errors import ProviderError
from regguard.core.logging import get_logger
from regguard.core.types import Completion, Usage
from regguard.providers.base import CompletionRequest

_log = get_logger(__name__)

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
_BODY_SNIPPET = 300


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: SecretStr | None,
        timeout_s: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        headers = {"X-Title": "RegressionGuard"}
        self._secret = api_key.get_secret_value() if api_key is not None else None
        if self._secret:
            headers["Authorization"] = f"Bearer {self._secret}"
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout_s)
        self._client.headers.update(headers)

    def _redact(self, text: str) -> str:
        """httpx error texts can quote request headers, i.e. the API key: never keep it."""
        return text.replace(self._secret, "***") if self._secret else text

    async def complete(self, request: CompletionRequest) -> Completion:
        payload = _build_payload(request)
        start = time.perf_counter()
        try:
            response = await self._client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError("request timed out", retryable=True) from exc
        except httpx.LocalProtocolError as exc:
            # Raised before sending, e.g. a key with a line break: its text quotes the header.
            raise ProviderError(
                "the request could not be sent: invalid header value "
                "(check REGGUARD_LLM_API_KEY for spaces or line breaks)",
                fatal=True,
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderError(
                f"transport error: {self._redact(str(exc))}", retryable=True
            ) from exc
        latency_ms = (time.perf_counter() - start) * 1000

        if response.status_code >= 400:
            raise _http_error(response)
        return _parse_response(response, request, latency_ms)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _build_payload(request: CompletionRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [m.model_dump() for m in request.messages],
        "temperature": request.temperature,
    }
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.seed is not None:
        payload["seed"] = request.seed
    if request.json_mode:
        payload["response_format"] = {"type": "json_object"}
    payload.update(request.extra)
    return payload


def _http_error(response: httpx.Response) -> ProviderError:
    status = response.status_code
    retry_after: float | None = None
    header = response.headers.get("retry-after")
    if header is not None:
        try:
            retry_after = float(header)
        except ValueError:
            retry_after = None  # HTTP-date form: let the executor use its own backoff
    return ProviderError(
        f"HTTP {status}: {_readable_error(response)}",
        retryable=status in _RETRYABLE_STATUS,
        status_code=status,
        retry_after_s=retry_after,
    )


def _readable_error(response: httpx.Response) -> str:
    """Prefer the human message (incl. OpenRouter's upstream ``metadata.raw``) over raw JSON."""
    try:
        body = response.json()
        error = body["error"]
        message = str(error.get("message", "")).strip()
        raw = (error.get("metadata") or {}).get("raw")
        if isinstance(raw, str) and raw.strip() and raw.strip() != message:
            message = f"{message}: {raw.strip()}" if message else raw.strip()
        if message:
            return message[:_BODY_SNIPPET]
    except (ValueError, KeyError, TypeError, AttributeError):
        pass
    return response.text[:_BODY_SNIPPET]


def _parse_response(
    response: httpx.Response, request: CompletionRequest, latency_ms: float
) -> Completion:
    try:
        body = response.json()
    except ValueError as exc:
        raise ProviderError("response body is not JSON", retryable=True) from exc

    # Some gateways (e.g. OpenRouter) report upstream failures as 200 + {"error": ...}.
    if isinstance(body, dict) and "error" in body:
        err = body["error"]
        code = err.get("code") if isinstance(err, dict) else None
        message = err.get("message", err) if isinstance(err, dict) else err
        status = code if isinstance(code, int) else None
        raise ProviderError(
            f"provider error: {str(message)[:_BODY_SNIPPET]}",
            retryable=status is None or status in _RETRYABLE_STATUS,
            status_code=status,
        )

    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("malformed response: no choices[0].message", retryable=True) from exc
    if not isinstance(text, str) or not text.strip():
        raise ProviderError("empty completion content", retryable=True)

    raw_usage = body.get("usage") or {}
    if not raw_usage:
        _log.warning("provider_missing_usage", model=request.model)
    usage = Usage(
        prompt_tokens=int(raw_usage.get("prompt_tokens") or 0),
        completion_tokens=int(raw_usage.get("completion_tokens") or 0),
    )
    return Completion(
        text=text,
        usage=usage,
        latency_ms=latency_ms,
        model=str(body.get("model") or request.model),
    )

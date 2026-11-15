"""Build the configured provider from settings."""

from regguard.core.config import Settings
from regguard.core.errors import ConfigError
from regguard.providers.base import LLMProvider
from regguard.providers.mock_provider import MockProvider, Responder
from regguard.providers.openai_compatible import OpenAICompatibleProvider


def build_provider(
    settings: Settings, *, mock_response: Responder | str | None = None
) -> LLMProvider:
    if settings.llm_provider == "mock":
        return MockProvider(mock_response) if mock_response is not None else MockProvider()
    if settings.llm_api_key is None:
        raise ConfigError(
            "REGGUARD_LLM_API_KEY is not set. Add it to your .env file "
            "(or set REGGUARD_LLM_PROVIDER=mock to run offline)."
        )
    return OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout_s=settings.request_timeout_s,
    )

import pytest

from regguard.apps.base import AppSpec
from regguard.apps.support_email import SPEC
from regguard.core.errors import ConfigError, ProviderError
from regguard.prompts.loader import load_prompt_version
from regguard.providers.mock_provider import MockProvider
from regguard.services.invoke import invoke_once
from tests.conftest import EXAMPLE_APP

PROMPT = load_prompt_version(EXAMPLE_APP / "prompts" / "classify", "v1")


async def test_valid_output() -> None:
    result = await invoke_once(
        spec=SPEC, prompt=PROMPT, provider=MockProvider(SPEC.mock_response), inputs={"email": "x"}
    )
    assert result.schema_valid
    assert result.parsed == {
        "category": "billing",
        "summary": "Customer reports a duplicate charge.",
    }


async def test_invalid_output_is_returned_not_raised() -> None:
    result = await invoke_once(
        spec=SPEC, prompt=PROMPT, provider=MockProvider('{"category": "x"}'), inputs={"email": "x"}
    )
    assert not result.schema_valid
    assert result.validation_error is not None
    assert result.completion.text == '{"category": "x"}'


async def test_provider_error_propagates() -> None:
    provider = MockProvider(lambda r: ProviderError("down", retryable=True))
    with pytest.raises(ProviderError):
        await invoke_once(spec=SPEC, prompt=PROMPT, provider=provider, inputs={"email": "x"})


async def test_incompatible_prompt_and_app() -> None:
    other = AppSpec(
        name="other", output_model=SPEC.output_model, input_variables=("text",), mock_response=""
    )
    with pytest.raises(ConfigError, match="inputs"):
        await invoke_once(spec=other, prompt=PROMPT, provider=MockProvider(), inputs={"text": "x"})

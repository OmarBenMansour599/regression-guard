"""Run the application under test once on a single input (manual smoke test / debugging)."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from regguard.apps.base import AppSpec, parse_output
from regguard.core.errors import ConfigError, DataValidationError
from regguard.core.types import Completion
from regguard.prompts.models import PromptConfig
from regguard.prompts.render import build_request
from regguard.providers.base import LLMProvider


@dataclass(frozen=True)
class InvokeResult:
    completion: Completion
    parsed: dict[str, Any] | None
    validation_error: str | None

    @property
    def schema_valid(self) -> bool:
        return self.parsed is not None


def ensure_compatible(spec: AppSpec, prompt: PromptConfig) -> None:
    if set(prompt.input_variables) != set(spec.input_variables):
        raise ConfigError(
            f"Prompt {prompt.id}@{prompt.version} uses inputs {list(prompt.input_variables)} "
            f"but app '{spec.name}' provides {list(spec.input_variables)}"
        )


async def invoke_once(
    *,
    spec: AppSpec,
    prompt: PromptConfig,
    provider: LLMProvider,
    inputs: Mapping[str, str],
    model_override: str | None = None,
) -> InvokeResult:
    """Call the provider once. ProviderError propagates; schema failures are returned."""
    ensure_compatible(spec, prompt)
    request = build_request(prompt, inputs, model_override=model_override)
    completion = await provider.complete(request)
    try:
        parsed = parse_output(completion.text, spec).model_dump(mode="json")
    except DataValidationError as exc:
        return InvokeResult(completion=completion, parsed=None, validation_error=str(exc))
    return InvokeResult(completion=completion, parsed=parsed, validation_error=None)

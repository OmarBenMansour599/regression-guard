"""Turn a prompt config + inputs into a provider request."""

from collections.abc import Mapping
from string import Template

from regguard.core.errors import DataValidationError
from regguard.prompts.models import PromptConfig
from regguard.providers.base import CompletionRequest, Message


def render_user_message(prompt: PromptConfig, inputs: Mapping[str, str]) -> str:
    expected = set(prompt.input_variables)
    given = set(inputs)
    if given != expected:
        missing, extra = sorted(expected - given), sorted(given - expected)
        raise DataValidationError(f"Prompt inputs mismatch: missing={missing} unexpected={extra}")
    # substitute() (not safe_substitute) so a missing value can never become a silent blank.
    return Template(prompt.user_template).substitute(inputs)


def render_messages(prompt: PromptConfig, inputs: Mapping[str, str]) -> tuple[Message, ...]:
    messages = [Message(role="system", content=prompt.system)]
    for example in prompt.few_shot:
        messages.append(Message(role="user", content=render_user_message(prompt, example.input)))
        messages.append(Message(role="assistant", content=example.output))
    messages.append(Message(role="user", content=render_user_message(prompt, inputs)))
    return tuple(messages)


def build_request(
    prompt: PromptConfig, inputs: Mapping[str, str], *, model_override: str | None = None
) -> CompletionRequest:
    params = prompt.model
    return CompletionRequest(
        model=model_override or params.model,
        messages=render_messages(prompt, inputs),
        temperature=params.temperature,
        max_tokens=params.max_tokens,
        seed=params.seed,
        json_mode=params.json_mode,
        extra=params.extra,
    )

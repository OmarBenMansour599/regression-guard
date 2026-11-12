from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from regguard.core.errors import DataValidationError
from regguard.prompts.loader import discover_prompts, load_prompt, load_prompt_version
from regguard.prompts.models import PromptConfig
from regguard.prompts.render import build_request, render_messages
from tests.conftest import EXAMPLE_APP

PROMPTS_DIR = EXAMPLE_APP / "prompts" / "classify"


def _raw(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "classify",
        "version": "v9",
        "model": {"model": "test/model"},
        "system": 'Reply with JSON like {"category": "..."}',
        "user_template": "Email: $email",
        "input_variables": ["email"],
    }
    data.update(overrides)
    return data


def _write(tmp_path: Path, data: dict[str, Any], name: str = "v9.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_example_prompts_are_valid() -> None:
    prompts = discover_prompts(PROMPTS_DIR)
    assert set(prompts) == {"v1", "v2"}
    assert prompts["v1"].content_hash != prompts["v2"].content_hash


def test_hash_is_stable_across_loads() -> None:
    a = load_prompt_version(PROMPTS_DIR, "v1")
    b = load_prompt_version(PROMPTS_DIR, "v1")
    assert a.content_hash == b.content_hash
    assert a.content_hash.startswith("sha256:")


def test_hash_ignores_description_but_not_model_params() -> None:
    base = PromptConfig.model_validate(_raw())
    described = PromptConfig.model_validate(_raw(description="new words", created_at="2026-01-01"))
    hotter = PromptConfig.model_validate(_raw(model={"model": "test/model", "temperature": 0.7}))
    other_model = PromptConfig.model_validate(_raw(model={"model": "test/other"}))
    assert described.content_hash == base.content_hash
    assert hotter.content_hash != base.content_hash
    assert other_model.content_hash != base.content_hash


def test_undeclared_placeholder_rejected() -> None:
    with pytest.raises(ValidationError, match="do not match"):
        PromptConfig.model_validate(_raw(user_template="$email from $sender"))


def test_few_shot_inputs_must_match_variables() -> None:
    with pytest.raises(ValidationError, match="few_shot"):
        PromptConfig.model_validate(_raw(few_shot=[{"input": {"text": "x"}, "output": "{}"}]))


def test_version_must_match_filename(tmp_path: Path) -> None:
    path = _write(tmp_path, _raw(version="v1"), name="v2.yaml")
    with pytest.raises(DataValidationError, match="must match"):
        load_prompt(path)


def test_invalid_yaml_reports_path(tmp_path: Path) -> None:
    path = tmp_path / "v9.yaml"
    path.write_text("id: [unclosed", encoding="utf-8")
    with pytest.raises(DataValidationError, match=r"v9\.yaml"):
        load_prompt(path)


def test_unknown_version_lists_available() -> None:
    with pytest.raises(DataValidationError, match="available: v1, v2"):
        load_prompt_version(PROMPTS_DIR, "v42")


def test_render_keeps_json_braces_and_dollar_values() -> None:
    prompt = PromptConfig.model_validate(_raw())
    messages = render_messages(prompt, {"email": "I paid $20 {twice}"})
    assert messages[0].content == 'Reply with JSON like {"category": "..."}'
    assert messages[-1].content == "Email: I paid $20 {twice}"


def test_render_orders_few_shot_examples() -> None:
    prompt = load_prompt_version(PROMPTS_DIR, "v1")
    messages = render_messages(prompt, {"email": "hello"})
    roles = [m.role for m in messages]
    assert roles == ["system", "user", "assistant", "user", "assistant", "user"]
    assert messages[-1].content.strip().endswith('"""')
    assert "hello" in messages[-1].content


def test_render_rejects_missing_or_extra_inputs() -> None:
    prompt = PromptConfig.model_validate(_raw())
    with pytest.raises(DataValidationError, match="missing"):
        render_messages(prompt, {})
    with pytest.raises(DataValidationError, match="unexpected"):
        render_messages(prompt, {"email": "x", "other": "y"})


def test_build_request_uses_prompt_params_and_override() -> None:
    prompt = load_prompt_version(PROMPTS_DIR, "v1")
    request = build_request(prompt, {"email": "x"})
    assert request.model == prompt.model.model
    assert request.json_mode is True
    assert request.seed == 42
    assert build_request(prompt, {"email": "x"}, model_override="other").model == "other"

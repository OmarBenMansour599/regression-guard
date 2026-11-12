from pathlib import Path

import pytest

from regguard.apps.base import extract_json, parse_output
from regguard.apps.config import load_app_config
from regguard.apps.registry import get_app
from regguard.apps.support_email import SPEC, SupportEmailOutput
from regguard.core.errors import ConfigError, DataValidationError
from tests.conftest import EXAMPLE_APP


@pytest.mark.parametrize(
    "text",
    [
        '{"category": "billing", "summary": "Refund request."}',
        '```json\n{"category": "billing", "summary": "Refund request."}\n```',
        'Sure! Here it is: {"category": "billing", "summary": "Refund request."} Thanks.',
    ],
)
def test_parse_valid_variants(text: str) -> None:
    out = parse_output(text, SPEC)
    assert isinstance(out, SupportEmailOutput)
    assert out.category == "billing"


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("no json here", "no JSON object"),
        ("{not json}", "not valid JSON"),
        ('{"category": "Billing", "summary": "x"}', "category"),
        ('{"category": "refunds", "summary": "x"}', "category"),
        ('{"category": "billing"}', "summary"),
        ('{"category": "billing", "summary": "x", "confidence": 0.9}', "confidence"),
        ('{"category": "billing", "summary": ""}', "summary"),
    ],
)
def test_parse_invalid_outputs(text: str, match: str) -> None:
    with pytest.raises(DataValidationError, match=match):
        parse_output(text, SPEC)


def test_extract_json_rejects_arrays() -> None:
    with pytest.raises(DataValidationError, match="object"):
        extract_json('[{"a": 1}]')


def test_mock_response_is_valid_for_its_app() -> None:
    parse_output(SPEC.mock_response, SPEC)


def test_registry() -> None:
    assert get_app("support_email_classifier") is SPEC
    with pytest.raises(ConfigError, match="Available"):
        get_app("nope")


def test_example_app_config_resolves_paths() -> None:
    cfg = load_app_config(EXAMPLE_APP / "regguard.yaml")
    assert cfg.app == "support_email_classifier"
    assert cfg.prompts_dir == (EXAMPLE_APP / "prompts" / "classify").resolve()
    assert cfg.judge is not None


def test_app_config_errors(tmp_path: Path) -> None:
    bad = tmp_path / "regguard.yaml"
    bad.write_text("name: x\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Invalid app config"):
        load_app_config(bad)
    with pytest.raises(ConfigError, match="Cannot read"):
        load_app_config(tmp_path / "missing.yaml")

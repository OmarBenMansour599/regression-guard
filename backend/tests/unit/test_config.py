from pathlib import Path

import pytest

from regguard.core.config import load_settings
from regguard.core.errors import ConfigError


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run in an empty dir (no .env) with no REGGUARD_* variables set."""
    monkeypatch.chdir(tmp_path)
    import os

    for key in list(os.environ):
        if key.startswith("REGGUARD_"):
            monkeypatch.delenv(key)


def test_defaults() -> None:
    s = load_settings()
    assert s.llm_api_key is None
    assert s.max_concurrency == 3
    assert s.log_format == "console"


def test_reads_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REGGUARD_MAX_CONCURRENCY", "8")
    monkeypatch.setenv("REGGUARD_LLM_MODEL", "some-model")
    s = load_settings()
    assert s.max_concurrency == 8
    assert s.llm_model == "some-model"


def test_secret_never_appears_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REGGUARD_LLM_API_KEY", "super-secret-value")
    s = load_settings()
    assert s.llm_api_key is not None
    assert s.llm_api_key.get_secret_value() == "super-secret-value"
    assert "super-secret-value" not in repr(s)
    assert "super-secret-value" not in str(s)


def test_invalid_value_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REGGUARD_MAX_CONCURRENCY", "0")
    with pytest.raises(ConfigError, match="max_concurrency"):
        load_settings()


def test_reads_dotenv_file(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("REGGUARD_LLM_MODEL=from-dotenv\n", encoding="utf-8")
    assert load_settings().llm_model == "from-dotenv"

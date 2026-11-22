from pathlib import Path

import pytest

from regguard.core.config import find_dotenv, load_settings
from regguard.core.errors import ConfigError

pytestmark = pytest.mark.usefixtures("isolated_env")


def test_defaults() -> None:
    s = load_settings()
    assert s.llm_api_key is None
    assert s.llm_provider == "openai_compatible"
    assert s.llm_base_url == "https://openrouter.ai/api/v1"
    assert s.max_concurrency == 3


def test_reads_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REGGUARD_MAX_CONCURRENCY", "8")
    monkeypatch.setenv("REGGUARD_LLM_PROVIDER", "mock")
    s = load_settings()
    assert s.max_concurrency == 8
    assert s.llm_provider == "mock"


def test_secret_never_appears_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REGGUARD_LLM_API_KEY", "super-secret-value")
    s = load_settings()
    assert s.llm_api_key is not None
    assert s.llm_api_key.get_secret_value() == "super-secret-value"
    assert "super-secret-value" not in repr(s)
    assert "super-secret-value" not in str(s)


@pytest.mark.parametrize("name", ["REGGUARD_LLM_API_KEY", "REGGUARD_SLACK_WEBHOOK_URL"])
def test_secrets_lose_surrounding_whitespace(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """A secret pasted with a trailing line break broke every CI call (2026-11-22)."""
    monkeypatch.setenv(name, "  sk-or-v1-abc\n")
    secret = getattr(load_settings(), name.removeprefix("REGGUARD_").lower())
    assert secret.get_secret_value() == "sk-or-v1-abc"


def test_blank_secret_means_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REGGUARD_LLM_API_KEY", " \n")
    assert load_settings().llm_api_key is None


def test_secret_with_inner_whitespace_is_refused_without_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REGGUARD_LLM_API_KEY", "sk-or-v1-abc\nsk-or-v1-def")
    with pytest.raises(ConfigError, match="llm_api_key") as info:
        load_settings()
    assert "sk-or" not in str(info.value)


def test_invalid_value_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REGGUARD_MAX_CONCURRENCY", "0")
    with pytest.raises(ConfigError, match="max_concurrency"):
        load_settings()


def test_reads_dotenv_in_cwd(isolated_env: Path) -> None:
    (isolated_env / ".env").write_text("REGGUARD_LLM_MODEL=from-dotenv\n", encoding="utf-8")
    assert load_settings().llm_model == "from-dotenv"


def test_env_var_beats_dotenv(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (isolated_env / ".env").write_text("REGGUARD_LLM_MODEL=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("REGGUARD_LLM_MODEL", "from-env")
    assert load_settings().llm_model == "from-env"


def test_find_dotenv_walks_up_to_repo_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sub = repo / "backend" / "src"
    sub.mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / ".env").write_text("X=1", encoding="utf-8")
    assert find_dotenv(sub) == repo / ".env"


def test_find_dotenv_does_not_escape_repo(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("X=1", encoding="utf-8")  # outside the repo
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    assert find_dotenv(repo) is None


def test_find_dotenv_outside_git_checks_only_start(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("X=1", encoding="utf-8")
    child = tmp_path / "child"
    child.mkdir()
    assert find_dotenv(child) is None

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_APP = REPO_ROOT / "examples" / "support-email-classifier"


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Empty working dir (no .env, no git repo) and no REGGUARD_* variables."""
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.startswith("REGGUARD_"):
            monkeypatch.delenv(key)
    return tmp_path

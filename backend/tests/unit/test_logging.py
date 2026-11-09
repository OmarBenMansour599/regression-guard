import json

import pytest

from regguard.core.logging import configure_logging, get_logger


def test_json_logging_emits_valid_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", "json")
    get_logger("t").info("run_started", run_id="r1")
    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "run_started"
    assert payload["run_id"] == "r1"
    assert payload["level"] == "info"


def test_level_filtering(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING", "json")
    get_logger("t").info("hidden")
    assert capsys.readouterr().out == ""

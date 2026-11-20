"""Slack messages, sending (faked transport, nothing leaves the machine), notify rules, CLI."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from regguard.apps.config import AppConfig, NotifyConfig
from regguard.cli.main import EXIT_CONFIG_ERROR, EXIT_GATE_FAILED, app
from regguard.comparison.verdict import compare
from regguard.core.config import Settings
from regguard.core.gating import GateConfig
from regguard.core.types import DriftReport, DriftStatus, MetricDrift, RunStatus, Verdict
from regguard.notifications import slack
from regguard.services.notify_service import (
    NotifyStatus,
    notify_check,
    notify_comparison,
    notify_drift,
    notify_run_error,
)
from regguard.storage.file_store import save_run
from tests.unit.run_factory import make_run, outcomes
from tests.unit.test_cli_run import config  # noqa: F401 - pytest fixture

WEBHOOK = "https://hooks.slack.test/services/T000/B000/SECRETTOKEN"
NOW = datetime(2026, 11, 20, tzinfo=UTC)
BASE = make_run(outcomes(30), run_id="base")
CAND = make_run(outcomes(30, fail=[1, 2, 3]), run_id="cand", critical=["email-0001"])
FAIL = compare(BASE, CAND, GateConfig(), baseline_name="main", now=NOW)
PASS = compare(BASE, BASE, GateConfig(), baseline_name="main", now=NOW)
runner = CliRunner()


def all_text(message: slack.SlackMessage) -> str:
    return json.dumps(message.payload())


# --- message building -----------------------------------------------------------------------


def test_comparison_message_content() -> None:
    message = slack.comparison_message(FAIL, CAND, report_path="reports/cand.html")
    text = all_text(message)
    assert message.text.startswith("RegressionGuard FAIL")
    assert ":x:" in text
    assert "critical_regression" in text
    assert "3 regressed case(s) (1 critical)" in text
    assert "`email-0001`" in text
    assert "reports/cand.html" in text


def test_messages_escape_slack_control_characters() -> None:
    assert slack.escape("<!channel> & <@U1>") == "&lt;!channel&gt; &amp; &lt;@U1&gt;"
    run = make_run(outcomes(2), app="<!channel>")
    assert "<!channel>" not in all_text(slack.comparison_message(PASS, run))


def test_messages_never_contain_inputs_or_outputs() -> None:
    run = CAND.model_copy(
        update={"cases": [c.model_copy(update={"raw_output": "RAW-SECRET"}) for c in CAND.cases]}
    )
    assert "RAW-SECRET" not in all_text(slack.comparison_message(FAIL, run))


def test_run_error_drift_and_check_messages() -> None:
    error = slack.run_error_message(make_run(outcomes(2), status=RunStatus.ERROR))
    assert "infrastructure, not quality" in all_text(error)
    assert "aborted" in all_text(error)
    drift = slack.drift_message(drift_report(new_episode=True))
    assert "DRIFT detected" in all_text(drift)
    assert "`label_exact`" in all_text(drift)
    assert "connected" in all_text(slack.connection_check_message())


# --- sending --------------------------------------------------------------------------------


def transport(status: int = 200, body: str = "ok", seen: list[httpx.Request] | None = None):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, text=body)

    return httpx.MockTransport(handler)


def test_send_posts_the_payload() -> None:
    seen: list[httpx.Request] = []
    slack.send(SecretStr(WEBHOOK), slack.connection_check_message(), transport=transport(seen=seen))
    assert len(seen) == 1
    assert str(seen[0].url) == WEBHOOK
    assert json.loads(seen[0].content)["text"] == "RegressionGuard test message"


def test_send_errors_never_reveal_the_webhook() -> None:
    with pytest.raises(slack.SlackError) as refused:
        slack.send(
            SecretStr(WEBHOOK),
            slack.connection_check_message(),
            transport=transport(404, f"no_service for {WEBHOOK}"),
        )
    assert "HTTP 404" in str(refused.value)
    assert "SECRETTOKEN" not in str(refused.value)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect to {request.url}")

    with pytest.raises(slack.SlackError) as unreachable:
        slack.send(
            SecretStr(WEBHOOK),
            slack.connection_check_message(),
            transport=httpx.MockTransport(boom),
        )
    assert "ConnectError" in str(unreachable.value)
    assert "SECRETTOKEN" not in str(unreachable.value)


def test_send_requires_https() -> None:
    with pytest.raises(slack.SlackError, match="https"):
        slack.send(SecretStr("http://insecure.test/hook"), slack.connection_check_message())


# --- notify rules ---------------------------------------------------------------------------


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[slack.SlackMessage]:
    """Replace the network call: record messages instead of posting them."""
    messages: list[slack.SlackMessage] = []

    def fake_send(url: SecretStr, message: slack.SlackMessage, **_: Any) -> None:
        assert url.get_secret_value() == WEBHOOK
        messages.append(message)

    monkeypatch.setattr(slack, "send", fake_send)
    return messages


def cfg(*events: str) -> AppConfig:
    notify = NotifyConfig(events=events) if events else NotifyConfig()  # type: ignore[arg-type]
    return AppConfig(name="t", app="support_email_classifier", prompts_dir=Path("."), notify=notify)


def test_example_config_notify_events_load_from_yaml() -> None:
    """Regression test: a bare `on:` key in YAML is read as the boolean True."""
    from regguard.apps.config import load_app_config
    from tests.conftest import EXAMPLE_APP

    assert load_app_config(EXAMPLE_APP / "regguard.yaml").notify.events == (
        "fail",
        "error",
        "drift",
    )


def configured() -> Settings:
    return Settings(llm_provider="mock", slack_webhook_url=SecretStr(WEBHOOK))


def test_fail_is_notified_pass_never(sent: list[slack.SlackMessage]) -> None:
    result = notify_comparison(cfg(), configured(), FAIL, CAND)
    assert result is not None
    assert result.status is NotifyStatus.SENT
    assert notify_comparison(cfg(), configured(), PASS, BASE) is None
    assert len(sent) == 1


def test_warn_only_when_configured(sent: list[slack.SlackMessage]) -> None:
    warn = FAIL.model_copy(update={"verdict": Verdict.WARN})
    assert notify_comparison(cfg(), configured(), warn, CAND) is None  # default: no warn
    result = notify_comparison(cfg("fail", "warn"), configured(), warn, CAND)
    assert result is not None
    assert result.status is NotifyStatus.SENT


def test_missing_webhook_is_reported_not_raised() -> None:
    result = notify_comparison(cfg(), Settings(llm_provider="mock"), FAIL, CAND)
    assert result is not None
    assert result.status is NotifyStatus.FAILED
    assert "REGGUARD_SLACK_WEBHOOK_URL" in result.message


def test_slack_failure_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_: Any, **__: Any) -> None:
        raise slack.SlackError("Slack answered HTTP 500: oops")

    monkeypatch.setattr(slack, "send", broken)
    result = notify_check(configured())
    assert result.status is NotifyStatus.FAILED
    assert "HTTP 500" in result.message


def test_run_error_notification(sent: list[slack.SlackMessage]) -> None:
    errored = make_run(outcomes(2), status=RunStatus.ERROR)
    assert notify_run_error(cfg("fail"), configured(), errored) is None  # error not enabled
    result = notify_run_error(cfg(), configured(), errored)
    assert result is not None
    assert result.status is NotifyStatus.SENT


def drift_report(*, new_episode: bool, gating: bool = True) -> DriftReport:
    status = DriftStatus.DRIFT if gating else DriftStatus.OK
    return DriftReport(
        app="t",
        baseline_run_id="base",
        baseline_name="main",
        status=status,
        comparable_runs=4,
        fresh_runs=4,
        latest_run_id="run-04",
        metrics=[
            MetricDrift(
                metric="label_exact",
                status=DriftStatus.DRIFT,
                reference=0.9,
                new_episode=new_episode,
                gating=gating,
                message="moving average 0.825 vs baseline 0.900",
            )
        ],
        created_at=NOW,
    )


def test_drift_alerts_once_per_episode(sent: list[slack.SlackMessage]) -> None:
    first = notify_drift(cfg(), configured(), drift_report(new_episode=True))
    assert first is not None
    assert first.status is NotifyStatus.SENT
    again = notify_drift(cfg(), configured(), drift_report(new_episode=False))
    assert again is not None
    assert again.status is NotifyStatus.SKIPPED
    assert notify_drift(cfg(), configured(), drift_report(new_episode=True, gating=False)) is None
    assert len(sent) == 1


# --- CLI ------------------------------------------------------------------------------------


def test_cli_compare_with_report_and_notify(
    config: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    sent: list[slack.SlackMessage],
) -> None:
    monkeypatch.setenv("REGGUARD_SLACK_WEBHOOK_URL", WEBHOOK)
    save_run(Path("runs"), BASE)
    save_run(Path("runs"), CAND)
    runner.invoke(app, ["baseline", "promote", "base", "-c", config])
    result = runner.invoke(app, ["compare", "cand", "--report", "--notify", "-c", config])
    assert result.exit_code == EXIT_GATE_FAILED, result.output  # reports never hide a FAIL
    assert "Report:  reports" in result.output
    assert "Slack notified" in result.output
    assert Path("reports/cand.html").is_file()
    assert Path("reports/cand.md").read_text(encoding="utf-8").startswith("## ❌")
    assert len(sent) == 1
    assert "reports" in all_text(sent[0])  # the report path is in the message


def test_cli_notify_without_webhook_warns_but_keeps_the_exit_code(config: str) -> None:  # noqa: F811
    save_run(Path("runs"), BASE)
    save_run(Path("runs"), CAND)
    runner.invoke(app, ["baseline", "promote", "base", "-c", config])
    result = runner.invoke(app, ["compare", "cand", "--notify", "-c", config])
    assert result.exit_code == EXIT_GATE_FAILED
    assert "Slack is not configured" in result.output


def test_cli_report_command(config: str) -> None:  # noqa: F811
    save_run(Path("runs"), CAND)
    without = runner.invoke(app, ["report", "cand", "-c", config])
    assert without.exit_code == 0, without.output
    assert "not found: the report has no comparison" in without.output
    assert Path("reports/cand.html").is_file()

    save_run(Path("runs"), BASE)
    runner.invoke(app, ["baseline", "promote", "base", "-c", config])
    with_cmp = runner.invoke(app, ["report", "cand", "-c", config])
    assert with_cmp.exit_code == 0, with_cmp.output  # a report is informational: exit 0
    assert "Verdict vs main: FAIL" in with_cmp.output
    assert "Dataset v1 changed since this run" in with_cmp.output  # factory runs: fake hash

    single = runner.invoke(app, ["report", "cand", "--no-compare", "-c", config])
    assert single.exit_code == 0
    assert "Verdict" not in single.output

    assert runner.invoke(app, ["report", "missing", "-c", config]).exit_code == EXIT_CONFIG_ERROR


def test_cli_run_with_report_writes_inputs(config: str) -> None:  # noqa: F811
    result = runner.invoke(app, ["run", "-p", "v1", "--report", "-c", config])
    assert result.exit_code == 0, result.output
    html = next(Path("reports").glob("*.html")).read_text(encoding="utf-8")
    assert "Hello, this is test email number" in html  # dataset inputs are shown


def test_cli_notify_test(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = runner.invoke(app, ["notify", "test"])
    assert missing.exit_code == EXIT_CONFIG_ERROR
    assert "docs/slack-setup.md" in missing.output

    messages: list[slack.SlackMessage] = []
    monkeypatch.setattr(slack, "send", lambda url, message, **_: messages.append(message))
    monkeypatch.setenv("REGGUARD_SLACK_WEBHOOK_URL", WEBHOOK)
    ok = runner.invoke(app, ["notify", "test"])
    assert ok.exit_code == 0, ok.output
    assert "Slack notified" in ok.output
    assert "SECRETTOKEN" not in ok.output
    assert len(messages) == 1

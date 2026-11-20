"""Notification use cases: decide whether an event deserves a Slack message, then send it.

A notification problem (no webhook configured, Slack down) is reported back as a result
and never changes a verdict or an exit code.
"""

from dataclasses import dataclass
from enum import StrEnum

from regguard.apps.config import AppConfig, NotifyEvent
from regguard.core.config import Settings
from regguard.core.types import Comparison, DriftReport, DriftStatus, RunResult, Verdict
from regguard.notifications import slack

SETUP_HINT = "set REGGUARD_SLACK_WEBHOOK_URL in .env (see docs/slack-setup.md)"


class NotifyStatus(StrEnum):
    SENT = "sent"
    SKIPPED = "skipped"  # nothing worth sending (e.g. drift episode already alerted)
    FAILED = "failed"  # not configured, or Slack refused / unreachable


@dataclass(frozen=True)
class NotifyResult:
    status: NotifyStatus
    message: str


def _deliver(settings: Settings, message: slack.SlackMessage) -> NotifyResult:
    if settings.slack_webhook_url is None:
        return NotifyResult(NotifyStatus.FAILED, f"Slack is not configured: {SETUP_HINT}")
    try:
        slack.send(settings.slack_webhook_url, message)
    except slack.SlackError as exc:
        return NotifyResult(NotifyStatus.FAILED, f"Slack notification failed: {exc}")
    return NotifyResult(NotifyStatus.SENT, "Slack notified")


def _wanted(config: AppConfig, event: NotifyEvent) -> bool:
    return event in config.notify.events


_VERDICT_EVENTS: dict[Verdict, NotifyEvent] = {
    Verdict.FAIL: "fail",
    Verdict.WARN: "warn",
    Verdict.ERROR: "error",
}


def notify_comparison(
    config: AppConfig,
    settings: Settings,
    comparison: Comparison,
    run: RunResult,
    *,
    report_path: str | None = None,
) -> NotifyResult | None:
    """None when this verdict is not configured to notify (PASS never notifies)."""
    event = _VERDICT_EVENTS.get(comparison.verdict)
    if event is None or not _wanted(config, event):
        return None
    message = slack.comparison_message(comparison, run, report_path=report_path)
    return _deliver(settings, message)


def notify_run_error(
    config: AppConfig, settings: Settings, run: RunResult, *, report_path: str | None = None
) -> NotifyResult | None:
    if not _wanted(config, "error"):
        return None
    return _deliver(settings, slack.run_error_message(run, report_path=report_path))


def notify_drift(config: AppConfig, settings: Settings, report: DriftReport) -> NotifyResult | None:
    """One message per drift episode: only when a gating metric just started drifting."""
    if report.status is not DriftStatus.DRIFT or not _wanted(config, "drift"):
        return None
    starting = [m for m in report.metrics if m.gating and m.status is DriftStatus.DRIFT]
    if not any(m.new_episode for m in starting):
        return NotifyResult(
            NotifyStatus.SKIPPED, "Drift continues: already alerted for this episode"
        )
    return _deliver(settings, slack.drift_message(report))


def notify_check(settings: Settings) -> NotifyResult:
    return _deliver(settings, slack.connection_check_message())

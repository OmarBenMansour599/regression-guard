"""Slack notifications through an incoming webhook (a secret URL that posts to one channel).

Messages never contain email text or raw model output (channels are widely read), and the
webhook URL never appears in output or errors: it is a credential.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import SecretStr

from regguard.core.errors import RegGuardError
from regguard.core.types import (
    CaseChange,
    Comparison,
    DriftReport,
    DriftStatus,
    RunResult,
    Severity,
    Verdict,
)

MAX_REASONS = 5
_ICONS = {
    Verdict.PASS: ":white_check_mark:",
    Verdict.WARN: ":warning:",
    Verdict.FAIL: ":x:",
    Verdict.ERROR: ":octagonal_sign:",
}


class SlackError(RegGuardError):
    """Sending to Slack failed. The message never includes the webhook URL."""


@dataclass(frozen=True)
class SlackMessage:
    text: str  # plain fallback (notifications, screen readers)
    blocks: list[dict[str, Any]] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        # The fallback text is rendered by Slack too: escape it, or "<!channel>" in an
        # app name would notify the whole channel.
        return {"text": escape(self.text), "blocks": self.blocks}


def escape(text: object) -> str:
    """Slack mrkdwn control characters (also stops accidental @channel-style mentions)."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _context(parts: Sequence[str]) -> dict[str, Any]:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": p} for p in parts]}


def _run_line(run: RunResult) -> str:
    m = run.meta
    return (
        f"*{escape(m.app)}* · prompt `{escape(m.prompt_version)}` · model `{escape(m.model)}` "
        f"· dataset `{escape(m.dataset_version)}` · {len({c.case_id for c in run.cases})} cases"
    )


def _footer(run: RunResult, report_path: str | None) -> dict[str, Any]:
    parts = [f"run `{escape(run.meta.run_id)}`"]
    if run.meta.git_sha:
        parts.append(f"git `{escape(run.meta.git_sha[:12])}`")
    if report_path:
        parts.append(f"report: `{escape(report_path)}`")
    return _context(parts)


def comparison_message(
    comparison: Comparison, run: RunResult, *, report_path: str | None = None
) -> SlackMessage:
    icon, verdict = _ICONS[comparison.verdict], comparison.verdict.value.upper()
    against = escape(comparison.baseline_name or comparison.baseline_run_id)
    reasons = [r for r in comparison.reasons if r.severity is not Severity.INFO][:MAX_REASONS]
    regressed = [d for d in comparison.cases if d.change is CaseChange.REGRESSED]
    blocks = [
        _section(f"{icon} *RegressionGuard: {verdict}* against baseline `{against}`"),
        _section(_run_line(run)),
    ]
    if reasons:
        blocks.append(
            _section(
                "\n".join(
                    f"• *{r.severity.value.upper()}* `{r.code}`: {escape(r.message)}"
                    for r in reasons
                )
            )
        )
    if regressed:
        critical = sum(1 for d in regressed if d.critical)
        ids = ", ".join(f"`{escape(d.case_id)}`" for d in regressed[:10])
        more = f" and {len(regressed) - 10} more" if len(regressed) > 10 else ""
        note = f" ({critical} critical)" if critical else ""
        blocks.append(_section(f"*{len(regressed)} regressed case(s){note}:* {ids}{more}"))
    blocks.append(_footer(run, report_path))
    text = f"RegressionGuard {verdict}: {run.meta.app} prompt {run.meta.prompt_version}"
    return SlackMessage(text=text, blocks=blocks)


def run_error_message(run: RunResult, *, report_path: str | None = None) -> SlackMessage:
    blocks = [
        _section(
            f"{_ICONS[Verdict.ERROR]} *RegressionGuard: run ERROR* (infrastructure, not quality)"
        ),
        _section(_run_line(run)),
        _section(f"> {escape(run.error or 'unknown error')}"),
        _footer(run, report_path),
    ]
    return SlackMessage(text=f"RegressionGuard run ERROR: {run.meta.app}", blocks=blocks)


def drift_message(report: DriftReport) -> SlackMessage:
    drifting = [m for m in report.metrics if m.status is DriftStatus.DRIFT and m.gating]
    lines = [f"• `{escape(m.metric)}`: {escape(m.message)}" for m in drifting]
    baseline = escape(report.baseline_name or report.baseline_run_id)
    blocks = [
        _section(
            f":chart_with_downwards_trend: *RegressionGuard: DRIFT detected* in "
            f"*{escape(report.app)}* (baseline `{baseline}`)"
        ),
        _section("\n".join(lines) or "No metric details."),
        _context(
            [
                f"{report.fresh_runs} fresh comparable run(s)",
                f"latest run `{escape(report.latest_run_id or '-')}`",
                "one alert per drift episode",
            ]
        ),
    ]
    return SlackMessage(text=f"RegressionGuard DRIFT: {report.app}", blocks=blocks)


def connection_check_message() -> SlackMessage:
    return SlackMessage(
        text="RegressionGuard test message",
        blocks=[
            _section(
                ":wave: *RegressionGuard is connected.* Regressions, failed runs and drift "
                "will be reported in this channel."
            )
        ],
    )


def send(
    webhook_url: SecretStr,
    message: SlackMessage,
    *,
    timeout_s: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """POST the message. Raises SlackError without ever revealing the URL."""
    url = webhook_url.get_secret_value()
    if not url.startswith("https://"):
        raise SlackError("The Slack webhook URL must start with https://")
    try:
        with httpx.Client(timeout=timeout_s, transport=transport) as client:
            response = client.post(url, json=message.payload())
    except httpx.HTTPError as exc:
        # str(exc) can contain the URL: report only the kind of failure.
        raise SlackError(f"Cannot reach Slack ({type(exc).__name__})") from None
    if response.status_code != 200:
        body = response.text[:200].replace(url, "<webhook>")
        raise SlackError(f"Slack answered HTTP {response.status_code}: {body}")

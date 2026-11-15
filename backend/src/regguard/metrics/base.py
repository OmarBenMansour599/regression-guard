"""Metric interface. Metrics are pure: no I/O, deterministic for the same input.

A *gating* metric decides whether a case passes. Informational metrics are recorded
and compared but never fail a case on their own.

``score`` returns ``None`` when the metric does not apply to a case (e.g. the label
cannot be checked because the output was not valid JSON). Such cases are left out of
that metric's average and of its paired comparison; another metric (``schema_valid``)
reports the underlying failure, so each problem is counted exactly once.

Scores are *binary* when ``passed`` is set (a rate is aggregated) and *continuous* when
``passed`` is None (a mean is aggregated, and comparisons count per-case drops).
"""

from dataclasses import dataclass
from typing import Any, Protocol

from regguard.core.types import MetricScore
from regguard.datasets.models import GoldenCase


@dataclass(frozen=True)
class ScoringInput:
    case: GoldenCase
    output: dict[str, Any] | None  # validated output, None if schema validation failed
    parse_error: str | None = None


class Metric(Protocol):
    name: str
    gating: bool

    def score(self, item: ScoringInput) -> MetricScore | None: ...

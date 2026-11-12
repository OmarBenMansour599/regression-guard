"""Metric interface. Metrics are pure: no I/O, deterministic for the same input.

A *gating* metric decides whether a case passes. Informational metrics are recorded
and compared (Phase 5) but never fail a case on their own.
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

    def score(self, item: ScoringInput) -> MetricScore: ...

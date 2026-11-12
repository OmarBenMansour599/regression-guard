"""Gate configuration: per-metric thresholds and hard rules (the ``gate:`` block of regguard.yaml).

Sign convention: a threshold's sign says which direction is bad.
- Negative (e.g. ``-0.03``): a *drop* of at least that much crosses it (accuracy-like metrics).
- Positive (e.g. ``+0.25``): a *rise* of at least that much crosses it (latency, tokens).

Units: ``absolute`` compares ``candidate - baseline`` (rates in 0..1, so -0.03 = -3 points);
``relative`` compares ``(candidate - baseline) / baseline`` (+0.25 = 25% higher).
"""

from fnmatch import fnmatchcase
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from regguard.core.types import FrozenModel


class MetricThreshold(FrozenModel):
    warn: float | None = None
    critical: float | None = None
    unit: Literal["absolute", "relative"] = "absolute"
    gating: bool = True  # False: crossings are reported as info and never change the verdict

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        values = [v for v in (self.warn, self.critical) if v is not None]
        if not values:
            raise ValueError("a threshold needs at least one of warn / critical")
        if any(v == 0 for v in values):
            raise ValueError("thresholds must be non-zero (the sign gives the bad direction)")
        if len({v > 0 for v in values}) > 1:
            raise ValueError("warn and critical must have the same sign")
        both = self.warn is not None and self.critical is not None
        if both and abs(self.critical or 0) < abs(self.warn or 0):
            raise ValueError("critical must be at least as large as warn")
        return self


def default_metric_thresholds() -> dict[str, MetricThreshold]:
    """Defaults from the technical plan, section 8."""
    return {
        "label_exact": MetricThreshold(warn=-0.03, critical=-0.08),
        "schema_valid": MetricThreshold(warn=-0.01, critical=-0.02),
        "label_exact/*": MetricThreshold(warn=-0.05, critical=-0.12),
        "latency_ms_p95": MetricThreshold(warn=0.25, unit="relative", gating=False),
        "tokens_per_case": MetricThreshold(warn=0.20, critical=0.50, unit="relative"),
    }


class GateConfig(FrozenModel):
    alpha: float = Field(default=0.10, gt=0.0, lt=1.0)
    min_regressed_cases: int = Field(default=3, ge=1)
    schema_valid_floor: float | None = Field(default=0.95, ge=0.0, le=1.0)
    critical_cases_must_not_regress: bool = True
    metrics: dict[str, MetricThreshold] = Field(default_factory=default_metric_thresholds)

    @field_validator("metrics", mode="after")
    @classmethod
    def _merge_with_defaults(cls, value: dict[str, MetricThreshold]) -> dict[str, MetricThreshold]:
        """Entries in regguard.yaml override or extend the defaults; they never drop them."""
        return {**default_metric_thresholds(), **value}

    def threshold_for(self, metric: str) -> MetricThreshold | None:
        """Exact name first, then glob patterns such as ``label_exact/*``."""
        if metric in self.metrics:
            return self.metrics[metric]
        for pattern, threshold in self.metrics.items():
            if any(ch in pattern for ch in "*?[") and fnmatchcase(metric, pattern):
                return threshold
        return None

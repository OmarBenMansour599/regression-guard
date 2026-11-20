"""Threshold arithmetic shared by the baseline verdict and drift detection. Pure.

A threshold's sign gives the bad direction (see ``core/gating.py``): negative means a drop
is bad, positive means a rise is bad.
"""

from regguard.core.gating import MetricThreshold
from regguard.core.types import ThresholdLevel

_EPS = 1e-9  # so that e.g. exactly -3 points counts as crossing a -0.03 threshold


def delta(reference: float, value: float, unit: str) -> float | None:
    """``value - reference`` (absolute) or its ratio to the reference (relative)."""
    if unit == "absolute":
        return value - reference
    return (value - reference) / reference if reference else None


def crossed(change: float, threshold: float | None) -> bool:
    if threshold is None:
        return False
    return change <= threshold + _EPS if threshold < 0 else change >= threshold - _EPS


def level(change: float | None, threshold: MetricThreshold | None) -> ThresholdLevel:
    if change is None or threshold is None:
        return ThresholdLevel.OK
    if crossed(change, threshold.critical):
        return ThresholdLevel.CRITICAL
    if crossed(change, threshold.warn):
        return ThresholdLevel.WARN
    return ThresholdLevel.OK


def fmt_delta(change: float | None, unit: str) -> str:
    if change is None:
        return "n/a"
    return f"{change * 100:+.1f} pts" if unit == "absolute" else f"{change * 100:+.0f}%"

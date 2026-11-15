"""Deterministic metrics: no LLM involved, fully reproducible."""

from regguard.core.types import MetricScore
from regguard.metrics.base import ScoringInput


class SchemaValid:
    """Output parsed as JSON and matched the app's output schema."""

    name = "schema_valid"
    gating = True

    def score(self, item: ScoringInput) -> MetricScore:
        ok = item.output is not None
        detail = {} if ok else {"error": item.parse_error or "invalid output"}
        return MetricScore(name=self.name, value=1.0 if ok else 0.0, passed=ok, detail=detail)


class LabelExact:
    """Categorical field matches the golden label exactly (e.g. email category).

    Not applicable when the output is invalid: that is a format failure, reported by
    ``schema_valid``, not a classification error.
    """

    gating = True

    def __init__(self, label_field: str) -> None:
        self.label_field = label_field
        self.name = "label_exact"

    def score(self, item: ScoringInput) -> MetricScore | None:
        if item.output is None:
            return None
        expected = item.case.expected.get(self.label_field)
        actual = item.output.get(self.label_field)
        ok = actual == expected
        return MetricScore(
            name=self.name,
            value=1.0 if ok else 0.0,
            passed=ok,
            detail={"expected": expected, "actual": actual},
        )

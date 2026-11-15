"""Per-label precision / recall / F1 and macro-F1 from (expected, predicted) label pairs.

Accuracy alone hides a minority class collapsing; these show it. Computed over cases
with a valid output only (invalid outputs are counted by ``schema_valid``).
"""

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class LabelStats:
    label: str
    tp: int
    fp: int
    fn: int

    @property
    def support(self) -> int:
        return self.tp + self.fn

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / self.support if self.support else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def label_stats(pairs: Iterable[tuple[str, str]]) -> list[LabelStats]:
    """One entry per label that appears as expected or predicted, sorted by label."""
    pairs = list(pairs)
    labels = sorted({e for e, _ in pairs} | {p for _, p in pairs})
    return [
        LabelStats(
            label=label,
            tp=sum(1 for e, p in pairs if e == label and p == label),
            fp=sum(1 for e, p in pairs if e != label and p == label),
            fn=sum(1 for e, p in pairs if e == label and p != label),
        )
        for label in labels
    ]


def macro_f1(stats: Iterable[LabelStats]) -> float:
    """Unweighted mean F1 over labels with at least one expected case."""
    present = [s.f1 for s in stats if s.support]
    return sum(present) / len(present) if present else 0.0

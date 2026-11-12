"""Dataset quality and privacy checks. Findings are warnings; ``--strict`` turns them into failures.

The PII detectors are heuristics meant to catch accidents, not a compliance tool.
Use fictional people and reserved domains (example.com, *.test) in test data.
"""

import re
from collections import Counter
from collections.abc import Iterator
from enum import StrEnum

from regguard.core.types import FrozenModel
from regguard.datasets.models import Dataset, Difficulty

_EMAIL = re.compile(r"\b[\w.+-]+@([\w-]+\.)+[A-Za-z]{2,}\b")
_RESERVED_DOMAIN = re.compile(
    r"@([\w-]+\.)*(example\.(com|org|net)|[\w-]+\.(test|example|invalid))$", re.I
)
_DIGIT_RUN = re.compile(r"(?<![\w])\+?\d[\d \-.()]{7,}\d(?![\w])")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
_SENTENCE_END = re.compile(r"[.!?](?=\s+[A-Z])")


class Severity(StrEnum):
    WARNING = "warning"


class Finding(FrozenModel):
    code: str
    message: str
    case_id: str | None = None
    severity: Severity = Severity.WARNING


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def find_pii(text: str) -> Iterator[tuple[str, str]]:
    """Yield (code, matched_text) for likely PII in ``text``."""
    for m in _EMAIL.finditer(text):
        if not _RESERVED_DOMAIN.search(m.group(0)):
            yield "pii_email", m.group(0)
    for m in _DIGIT_RUN.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            yield "pii_card_number", m.group(0)
        elif 9 <= len(digits) <= 15:
            yield "pii_phone", m.group(0)
    for m in _IBAN.finditer(text):
        yield "pii_iban", m.group(0)


def _mask(value: str) -> str:
    return value[:3] + "***" if len(value) > 3 else "***"


def lint_dataset(
    dataset: Dataset,
    *,
    label_field: str | None = None,
    summary_field: str | None = None,
    min_cases: int = 50,
) -> list[Finding]:
    findings: list[Finding] = []
    cases = dataset.cases

    if len(cases) < min_cases:
        findings.append(
            Finding(
                code="too_few_cases",
                message=f"{len(cases)} cases; at least {min_cases} recommended",
            )
        )

    seen_inputs: dict[str, str] = {}
    for case in cases:
        for field, text in case.input.items():
            for code, match in find_pii(text):
                findings.append(
                    Finding(code=code, case_id=case.id, message=f"input.{field}: {_mask(match)}")
                )
        normalized = " ".join(" ".join(case.input.values()).lower().split())
        if normalized in seen_inputs:
            findings.append(
                Finding(
                    code="duplicate_input",
                    case_id=case.id,
                    message=f"same input as {seen_inputs[normalized]}",
                )
            )
        seen_inputs.setdefault(normalized, case.id)

        if summary_field and isinstance(case.expected.get(summary_field), str):
            summary = case.expected[summary_field]
            if _SENTENCE_END.search(summary.strip()):
                findings.append(
                    Finding(
                        code="multi_sentence_summary",
                        case_id=case.id,
                        message="expected summary should be one sentence",
                    )
                )
        if case.difficulty is Difficulty.HARD and not case.notes.strip():
            findings.append(
                Finding(
                    code="hard_case_without_notes",
                    case_id=case.id,
                    message="explain in notes why this case is hard",
                )
            )

    if label_field and cases:
        counts = Counter(str(c.expected.get(label_field)) for c in cases)
        fair_share = len(cases) / len(counts)
        for label, n in sorted(counts.items()):
            if n < 0.5 * fair_share:
                findings.append(
                    Finding(
                        code="label_imbalance",
                        message=f"'{label}' has {n} cases (fair share ~{fair_share:.0f})",
                    )
                )
    return findings


def dataset_stats(dataset: Dataset, *, label_field: str | None = None) -> dict[str, dict[str, int]]:
    cases = dataset.cases
    stats: dict[str, dict[str, int]] = {
        "difficulty": dict(Counter(c.difficulty.value for c in cases)),
        "tags": dict(Counter(t for c in cases for t in c.tags).most_common()),
        "flags": {"total": len(cases), "critical": sum(c.critical for c in cases)},
    }
    if label_field:
        stats["labels"] = dict(Counter(str(c.expected.get(label_field)) for c in cases))
    return stats

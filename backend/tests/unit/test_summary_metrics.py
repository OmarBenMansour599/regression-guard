"""Deterministic summary checks and lexical similarity."""

import pytest

from regguard.datasets.models import Difficulty, GoldenCase
from regguard.metrics.base import ScoringInput
from regguard.metrics.summary import (
    SummaryFormat,
    SummarySimilarity,
    content_words,
    copied_share,
    overlap_f1,
    sentence_count,
)

EMAIL = (
    "Hello, I was charged twice for my annual plan last week and I would like one of the "
    "two charges to be refunded as soon as possible. Thanks, Omar"
)
CASE = GoldenCase(
    id="email-0001",
    input={"email": EMAIL},
    expected={
        "category": "billing",
        "summary": "Customer was charged twice for the annual plan and asks for a refund.",
    },
    difficulty=Difficulty.EASY,
)


def item(summary: str | None) -> ScoringInput:
    output = None if summary is None else {"category": "billing", "summary": summary}
    return ScoringInput(case=CASE, output=output)


# --- helpers ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "n"),
    [
        ("Customer asks for a refund.", 1),
        ("Customer asks for a refund", 1),
        ("Customer asks. They want a refund.", 2),
        ("Is it broken? Yes! Fix it.", 3),
        ("Version 2.0 of the app crashes at startup.", 1),  # "2.0" is not a sentence end
    ],
)
def test_sentence_count(text: str, n: int) -> None:
    assert sentence_count(text) == n


def test_copied_share_detects_pasted_input() -> None:
    pasted = "I was charged twice for my annual plan last week and I would like one of the two"
    assert copied_share(pasted, [EMAIL]) == 1.0
    assert copied_share("Customer was charged twice and wants a refund.", [EMAIL]) == 0.0
    assert copied_share("Short.", [EMAIL]) == 0.0  # fewer than 8 words: no n-grams


def test_content_words_drop_stopwords_and_customer_opening() -> None:
    assert content_words("The customer is asking for a refund.") == {"asking", "refund"}
    assert content_words("Customer asks for a refund.") == {"asks", "refund"}


def test_overlap_f1() -> None:
    assert overlap_f1("Customer wants a refund.", "Customer asks for a refund.") == pytest.approx(
        2 * 1 / (2 + 2)
    )
    assert overlap_f1("Customer wants a refund.", "Customer wants a refund.") == 1.0
    assert overlap_f1("", "Customer wants a refund.") == 0.0


# --- SummaryFormat --------------------------------------------------------------------------


def test_good_summary_passes() -> None:
    score = SummaryFormat("summary").score(
        item("The customer was charged twice and wants a refund.")
    )
    assert score is not None
    assert score.passed is True
    assert score.detail["problems"] == []


@pytest.mark.parametrize(
    ("summary", "problem"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("Refund please.", "too_short"),
        ("word " * 41, "too_long"),
        ("Customer was charged twice. They want a refund now.", "multiple_sentences"),
        ("Customer was charged twice\nand wants a refund.", "multiple_lines"),
        (
            "I was charged twice for my annual plan last week and I would like one of the two "
            "charges to be refunded.",
            "copied_from_input",
        ),
    ],
)
def test_bad_summaries_fail_with_a_reason(summary: str, problem: str) -> None:
    score = SummaryFormat("summary").score(item(summary))
    assert score is not None
    assert score.passed is False
    assert problem in score.detail["problems"]


def test_format_not_applicable_without_valid_output() -> None:
    assert SummaryFormat("summary").score(item(None)) is None
    assert SummarySimilarity("summary").score(item(None)) is None


# --- SummarySimilarity ----------------------------------------------------------------------


def test_similarity_is_continuous_and_informational() -> None:
    metric = SummarySimilarity("summary")
    assert metric.gating is False
    score = metric.score(item("The customer is charged twice for the annual plan, refund asked."))
    assert score is not None
    assert score.passed is None
    assert 0.5 < score.value < 1.0


def test_similarity_not_applicable_without_reference() -> None:
    case = CASE.model_copy(update={"expected": {"category": "billing"}})
    assert (
        SummarySimilarity("summary").score(ScoringInput(case=case, output={"summary": "x"})) is None
    )

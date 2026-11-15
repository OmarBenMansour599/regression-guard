"""Deterministic checks on a free-text summary field. Pure, no LLM.

``summary_format`` (gating): the output contract, one sentence of reasonable length that
is not a copy of the input.
``summary_similarity`` (informational): word-overlap F1 with the human reference, after
normalisation. Wording legitimately differs ("Customer asks..." vs "The customer is
asking..."), so this is a weak signal; the LLM judge (Phase 5b-2) scores meaning.
"""

import re
from collections.abc import Iterable

from regguard.core.types import MetricScore
from regguard.metrics.base import ScoringInput

_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?", re.UNICODE)
_SENTENCE_END = re.compile(r"[.!?]+(?:\s|$)")

MIN_WORDS = 5
MAX_WORDS = 40
_COPY_NGRAM = 8
_COPY_SHARE = 0.5  # share of the summary's 8-grams found verbatim in the input -> copied

_STOPWORD_TEXT = (
    "a an the and or but of to in on at for with from by as is are was were be been being "
    "this that these those it its their his her they them he she we you i about into over "
    "after before has have had having do does did not no so than then there here also "
    "will would can could should may might"
)
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())
_LEADING = re.compile(r"^(?:the\s+)?(?:customer|user|client|sender)\s+(?:is\s+|was\s+)?", re.I)


def words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def _ngrams(tokens: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def sentence_count(text: str) -> int:
    """Rough count: terminal punctuation followed by a space or the end. Never below 1."""
    return max(1, len(_SENTENCE_END.findall(text.strip())))


def copied_share(summary: str, sources: Iterable[str], n: int = _COPY_NGRAM) -> float:
    """Share of the summary's word n-grams that occur verbatim in any source text."""
    grams = _ngrams(words(summary), n)
    if not grams:
        return 0.0
    source_grams: set[tuple[str, ...]] = set()
    for source in sources:
        source_grams |= _ngrams(words(source), n)
    return len(grams & source_grams) / len(grams)


def content_words(text: str) -> set[str]:
    """Lowercased words minus stopwords and the conventional "Customer ..." opening."""
    return {w for w in words(_LEADING.sub("", text.strip())) if w not in _STOPWORDS}


def overlap_f1(candidate: str, reference: str) -> float:
    a, b = content_words(candidate), content_words(reference)
    if not a or not b:
        return 0.0
    common = len(a & b)
    return 2 * common / (len(a) + len(b))


class SummaryFormat:
    """The summary is one sentence, 5-40 words, not pasted from the input."""

    name = "summary_format"
    gating = True

    def __init__(self, summary_field: str) -> None:
        self.summary_field = summary_field

    def score(self, item: ScoringInput) -> MetricScore | None:
        if item.output is None:
            return None
        summary = str(item.output.get(self.summary_field) or "")
        n_words = len(words(summary))
        problems = []
        if not summary.strip():
            problems.append("empty")
        else:
            if "\n" in summary.strip():
                problems.append("multiple_lines")
            if sentence_count(summary) > 1:
                problems.append("multiple_sentences")
            if n_words < MIN_WORDS:
                problems.append("too_short")
            elif n_words > MAX_WORDS:
                problems.append("too_long")
            sources = [str(v) for v in item.case.input.values()]
            if copied_share(summary, sources) >= _COPY_SHARE:
                problems.append("copied_from_input")
        ok = not problems
        return MetricScore(
            name=self.name,
            value=1.0 if ok else 0.0,
            passed=ok,
            detail={"words": n_words, "problems": problems},
        )


class SummarySimilarity:
    """Content-word overlap F1 between the summary and the reference (0..1, informational)."""

    name = "summary_similarity"
    gating = False

    def __init__(self, summary_field: str) -> None:
        self.summary_field = summary_field

    def score(self, item: ScoringInput) -> MetricScore | None:
        reference = item.case.expected.get(self.summary_field)
        if item.output is None or not isinstance(reference, str):
            return None
        candidate = str(item.output.get(self.summary_field) or "")
        return MetricScore(name=self.name, value=overlap_f1(candidate, reference), passed=None)

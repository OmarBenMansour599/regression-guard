import pytest

from regguard.comparison.stats import (
    binomial_tail,
    mcnemar_one_sided,
    min_regressions_for_significance,
)


@pytest.mark.parametrize(
    ("k", "n", "expected"),
    [
        (0, 5, 1.0),
        (6, 5, 0.0),
        (3, 3, 0.125),  # 1/8
        (4, 4, 0.0625),  # 1/16
        (2, 3, 0.5),  # (3 + 1) / 8
        (4, 5, 0.1875),  # (5 + 1) / 32
        (8, 10, 0.0546875),  # (45 + 10 + 1) / 1024
    ],
)
def test_binomial_tail_matches_hand_computed_values(k: int, n: int, expected: float) -> None:
    assert binomial_tail(k, n) == pytest.approx(expected)


def test_mcnemar_no_flips_is_not_significant() -> None:
    assert mcnemar_one_sided(0, 0) == 1.0


def test_mcnemar_only_improvements_is_not_significant() -> None:
    assert mcnemar_one_sided(0, 5) == 1.0


def test_mcnemar_three_one_way_regressions() -> None:
    assert mcnemar_one_sided(3, 0) == pytest.approx(0.125)


def test_mcnemar_improvements_offset_regressions() -> None:
    assert mcnemar_one_sided(4, 0) < 0.10
    assert mcnemar_one_sided(4, 2) > 0.10  # (15 + 6 + 1) / 64 = 0.34


def test_min_regressions_for_significance() -> None:
    assert min_regressions_for_significance(0.10) == 4
    assert min_regressions_for_significance(0.05) == 5


@pytest.mark.parametrize("bad", [(-1, 3), (2, -1)])
def test_negative_counts_rejected(bad: tuple[int, int]) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        mcnemar_one_sided(*bad)


def test_bad_alpha_rejected() -> None:
    with pytest.raises(ValueError, match="alpha"):
        min_regressions_for_significance(1.0)


def test_binomial_tail_rejects_negative() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        binomial_tail(-1, 3)

import pytest

from regguard.metrics.classification import label_stats, macro_f1

# expected, predicted
PAIRS = [
    ("billing", "billing"),
    ("billing", "billing"),
    ("billing", "technical"),
    ("technical", "technical"),
    ("technical", "billing"),
    ("account", "account"),
    ("general", "account"),
]


def test_label_stats_hand_computed() -> None:
    by_label = {s.label: s for s in label_stats(PAIRS)}
    billing = by_label["billing"]
    assert (billing.tp, billing.fp, billing.fn) == (2, 1, 1)
    assert billing.precision == pytest.approx(2 / 3)
    assert billing.recall == pytest.approx(2 / 3)
    assert billing.f1 == pytest.approx(2 / 3)
    account = by_label["account"]
    assert (account.tp, account.fp, account.fn) == (1, 1, 0)
    assert account.precision == 0.5
    assert account.recall == 1.0
    general = by_label["general"]
    assert general.recall == 0.0
    assert general.precision == 0.0  # never predicted: defined as 0, not an error
    assert general.f1 == 0.0


def test_macro_f1_averages_labels_with_support() -> None:
    stats = label_stats(PAIRS)
    expected = (2 / 3 + 0.5 + 2 / 3 + 0.0) / 4  # billing, technical, account, general
    assert macro_f1(stats) == pytest.approx(expected)


def test_predicted_only_label_does_not_count_in_macro_f1() -> None:
    stats = label_stats([("billing", "billing"), ("billing", "spam")])
    assert {s.label for s in stats} == {"billing", "spam"}
    assert macro_f1(stats) == pytest.approx(2 * 1.0 * 0.5 / 1.5)  # billing only


def test_empty() -> None:
    assert label_stats([]) == []
    assert macro_f1([]) == 0.0

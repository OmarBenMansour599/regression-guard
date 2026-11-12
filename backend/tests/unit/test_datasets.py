from pathlib import Path
from typing import Any

import pytest
import yaml

from regguard.apps.support_email import SPEC
from regguard.core.errors import DataValidationError
from regguard.datasets.lint import dataset_stats, find_pii, lint_dataset
from regguard.datasets.loader import list_versions, load_dataset, resolve_version
from regguard.datasets.models import Dataset, Difficulty
from regguard.datasets.select import select_cases

CATEGORIES = ("billing", "technical", "account", "general")


def make_case(i: int, category: str = "billing", **overrides: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "id": f"email-{i:04d}",
        "input": {"email": f"Hello, this is test email number {i} about {category}."},
        "expected": {"category": category, "summary": f"Customer writes about {category}."},
        "difficulty": "easy",
        "tags": [],
        "notes": "",
    }
    case.update(overrides)
    return case


def balanced_cases(per_category: int = 3) -> list[dict[str, Any]]:
    cases, i = [], 1
    for category in CATEGORIES:
        for _ in range(per_category):
            cases.append(make_case(i, category))
            i += 1
    return cases


def write_dataset(
    root: Path, cases: Any, version: str = "v1", manifest: dict[str, Any] | None = None
) -> Path:
    directory = root / version
    directory.mkdir(parents=True)
    meta = manifest or {"name": "emails", "version": version}
    (directory / "dataset.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")
    (directory / "cases.yaml").write_text(yaml.safe_dump(cases), encoding="utf-8")
    return directory


def load(directory: Path) -> Dataset:
    return load_dataset(
        directory, output_model=SPEC.output_model, input_variables=SPEC.input_variables
    )


# --- loading -----------------------------------------------------------------


def test_load_valid_dataset(tmp_path: Path) -> None:
    ds = load(write_dataset(tmp_path, balanced_cases()))
    assert len(ds.cases) == 12
    assert ds.manifest.version == "v1"
    assert ds.get("email-0001").difficulty is Difficulty.EASY


def test_all_problems_reported_at_once(tmp_path: Path) -> None:
    cases = [
        make_case(1),
        make_case(1),  # duplicate id
        make_case(2, "refunds"),  # invalid category
        make_case(3, input={"text": "wrong key"}),
        make_case(4, difficulty="extreme"),
        make_case(5, expected={"category": "billing"}),  # missing summary
    ]
    with pytest.raises(DataValidationError) as info:
        load(write_dataset(tmp_path, cases))
    message = str(info.value)
    assert "5 problem(s)" in message
    for fragment in ("duplicate id", "category", "input keys", "difficulty", "summary"):
        assert fragment in message


def test_empty_cases_file(tmp_path: Path) -> None:
    with pytest.raises(DataValidationError, match="no cases yet"):
        load(write_dataset(tmp_path, []))


def test_version_must_match_folder(tmp_path: Path) -> None:
    directory = write_dataset(tmp_path, balanced_cases(), manifest={"name": "e", "version": "v2"})
    with pytest.raises(DataValidationError, match="must match"):
        load(directory)


def test_yaml_syntax_error_is_reported(tmp_path: Path) -> None:
    directory = write_dataset(tmp_path, balanced_cases())
    (directory / "cases.yaml").write_text("- id: [unclosed", encoding="utf-8")
    with pytest.raises(DataValidationError, match="YAML syntax error"):
        load(directory)


def test_invalid_tags_rejected(tmp_path: Path) -> None:
    with pytest.raises(DataValidationError, match="snake_case"):
        load(write_dataset(tmp_path, [make_case(1, tags=["Mixed Language"])]))


def test_expected_output_is_normalized(tmp_path: Path) -> None:
    case = make_case(1, expected={"category": "billing", "summary": "  Customer pays.  "})
    ds = load(write_dataset(tmp_path, [case]))
    assert ds.cases[0].expected["summary"] == "Customer pays."


def test_versions_sorted_naturally(tmp_path: Path) -> None:
    for version in ("v1", "v10", "v2"):
        write_dataset(tmp_path, balanced_cases(), version=version)
    assert list_versions(tmp_path) == ["v1", "v2", "v10"]
    assert resolve_version(tmp_path, None) == "v10"
    with pytest.raises(DataValidationError, match="available"):
        resolve_version(tmp_path, "v3")


# --- hashing -----------------------------------------------------------------


def test_hash_stable_and_order_independent(tmp_path: Path) -> None:
    cases = balanced_cases()
    a = load(write_dataset(tmp_path / "a", cases))
    b = load(write_dataset(tmp_path / "b", list(reversed(cases))))
    assert a.content_hash == b.content_hash


def test_hash_changes_with_labels_but_not_notes(tmp_path: Path) -> None:
    base = balanced_cases()
    relabeled = [dict(c) for c in base]
    relabeled[0] = make_case(1, "technical")
    renoted = [dict(c) for c in base]
    renoted[0] = {**base[0], "notes": "new explanation"}
    h_base = load(write_dataset(tmp_path / "a", base)).content_hash
    h_label = load(write_dataset(tmp_path / "b", relabeled)).content_hash
    h_notes = load(write_dataset(tmp_path / "c", renoted)).content_hash
    assert h_label != h_base
    assert h_notes == h_base


# --- lint --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("write to jane.doe@gmail.com", "pii_email"),
        ("call me at +33 6 12 34 56 78", "pii_phone"),
        ("my card 4111 1111 1111 1111 was charged", "pii_card_number"),
        ("IBAN FR76 3000 6000 0112 3456 7890 189", "pii_iban"),
    ],
)
def test_pii_detected(text: str, code: str) -> None:
    assert code in {c for c, _ in find_pii(text)}


@pytest.mark.parametrize(
    "text",
    [
        "contact jane@example.com",
        "billing@shop.test",
        "order 12345 on 2026-01-01",
        "invoice INV-2026-0042",
    ],
)
def test_pii_not_flagged(text: str) -> None:
    assert list(find_pii(text)) == []


def test_lint_quality_findings(tmp_path: Path) -> None:
    cases = balanced_cases()
    cases.append(make_case(13, input=cases[0]["input"]))  # duplicate input
    cases.append(
        make_case(
            14,
            expected={"category": "general", "summary": "Customer asks. Then asks again."},
            difficulty="hard",
        )
    )
    findings = lint_dataset(
        load(write_dataset(tmp_path, cases)),
        label_field="category",
        summary_field="summary",
        min_cases=50,
    )
    codes = {f.code for f in findings}
    assert codes == {
        "too_few_cases",
        "duplicate_input",
        "multi_sentence_summary",
        "hard_case_without_notes",
    }


def test_lint_label_imbalance(tmp_path: Path) -> None:
    cases = [make_case(i, "billing") for i in range(1, 10)] + [make_case(10, "general")]
    findings = lint_dataset(load(write_dataset(tmp_path, cases)), label_field="category")
    assert any(f.code == "label_imbalance" and "general" in f.message for f in findings)


def test_lint_clean_dataset_has_no_findings(tmp_path: Path) -> None:
    ds = load(write_dataset(tmp_path, balanced_cases()))
    assert lint_dataset(ds, label_field="category", summary_field="summary", min_cases=12) == []


def test_stats(tmp_path: Path) -> None:
    cases = balanced_cases()
    cases[0] = make_case(1, tags=["typo", "short"], critical=True)
    stats = dataset_stats(load(write_dataset(tmp_path, cases)), label_field="category")
    assert stats["labels"] == {c: 3 for c in CATEGORIES}
    assert stats["flags"] == {"total": 12, "critical": 1}
    assert stats["tags"] == {"typo": 1, "short": 1}


# --- selection ---------------------------------------------------------------


def test_stratified_limit_keeps_balance(tmp_path: Path) -> None:
    ds = load(write_dataset(tmp_path, balanced_cases(per_category=5)))
    subset = select_cases(ds.cases, limit=8, label_field="category", seed=1)
    labels = [c.expected["category"] for c in subset]
    assert len(subset) == 8
    assert all(labels.count(c) == 2 for c in CATEGORIES)


def test_selection_is_deterministic_and_ordered(tmp_path: Path) -> None:
    ds = load(write_dataset(tmp_path, balanced_cases(per_category=5)))
    a = select_cases(ds.cases, limit=6, label_field="category", seed=7)
    b = select_cases(ds.cases, limit=6, label_field="category", seed=7)
    assert a == b
    assert [c.id for c in a] == sorted(c.id for c in a)


def test_select_by_ids_and_tags(tmp_path: Path) -> None:
    cases = balanced_cases()
    cases[2] = make_case(3, tags=["typo"])
    ds = load(write_dataset(tmp_path, cases))
    assert [c.id for c in select_cases(ds.cases, tags=["typo"])] == ["email-0003"]
    assert [c.id for c in select_cases(ds.cases, ids=["email-0002"])] == ["email-0002"]
    with pytest.raises(DataValidationError, match="Unknown case ids"):
        select_cases(ds.cases, ids=["email-9999"])


def test_limit_larger_than_dataset_returns_all(tmp_path: Path) -> None:
    ds = load(write_dataset(tmp_path, balanced_cases()))
    assert len(select_cases(ds.cases, limit=100)) == 12

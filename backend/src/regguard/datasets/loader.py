"""Load and validate a dataset version. Reports ALL problems at once (hand-authored data)."""

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from regguard.core.errors import DataValidationError
from regguard.datasets.models import Dataset, DatasetManifest, GoldenCase

MANIFEST_FILE = "dataset.yaml"
CASES_FILE = "cases.yaml"


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DataValidationError(f"Cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise DataValidationError(f"YAML syntax error in {path}:\n{exc}") from exc


def _errors(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()
    )


def _version_key(version: str) -> tuple[int, str]:
    digits = re.findall(r"\d+", version)
    return (int(digits[0]) if digits else -1, version)


def list_versions(datasets_dir: Path) -> list[str]:
    """Dataset versions in ``datasets_dir``, oldest first (v2 < v10)."""
    if not datasets_dir.is_dir():
        raise DataValidationError(f"Dataset directory not found: {datasets_dir}")
    versions = [d.name for d in datasets_dir.iterdir() if (d / MANIFEST_FILE).is_file()]
    return sorted(versions, key=_version_key)


def resolve_version(datasets_dir: Path, version: str | None) -> str:
    versions = list_versions(datasets_dir)
    if not versions:
        raise DataValidationError(f"No dataset versions found in {datasets_dir}")
    if version is None:
        return versions[-1]
    if version not in versions:
        raise DataValidationError(
            f"Dataset version '{version}' not found (available: {', '.join(versions)})"
        )
    return version


def load_dataset(
    directory: Path,
    *,
    output_model: type[BaseModel],
    input_variables: Sequence[str],
) -> Dataset:
    """Load ``directory`` (one dataset version) and validate it against the app contract."""
    raw_manifest = _read_yaml(directory / MANIFEST_FILE)
    if not isinstance(raw_manifest, dict):
        raise DataValidationError(f"{directory / MANIFEST_FILE} must be a YAML mapping")
    try:
        manifest = DatasetManifest.model_validate(raw_manifest)
    except ValidationError as exc:
        raise DataValidationError(f"Invalid {MANIFEST_FILE}: {_errors(exc)}") from exc
    if manifest.version != directory.name:
        raise DataValidationError(
            f"{MANIFEST_FILE} declares version '{manifest.version}' but the folder is "
            f"'{directory.name}'; they must match"
        )

    raw_cases = _read_yaml(directory / CASES_FILE)
    if not raw_cases:
        raise DataValidationError(f"{directory / CASES_FILE} has no cases yet")
    if not isinstance(raw_cases, list):
        raise DataValidationError(f"{CASES_FILE} must be a YAML list of cases")

    problems: list[str] = []
    cases: list[GoldenCase] = []
    seen: set[str] = set()
    expected_inputs = set(input_variables)

    for index, raw in enumerate(raw_cases):
        label = raw.get("id", f"#{index + 1}") if isinstance(raw, dict) else f"#{index + 1}"
        try:
            case = GoldenCase.model_validate(raw)
        except ValidationError as exc:
            problems.append(f"[{label}] {_errors(exc)}")
            continue
        if case.id in seen:
            problems.append(f"[{case.id}] duplicate id")
        seen.add(case.id)
        if set(case.input) != expected_inputs:
            problems.append(
                f"[{case.id}] input keys {sorted(case.input)} != expected {sorted(expected_inputs)}"
            )
        if any(not v.strip() for v in case.input.values()):
            problems.append(f"[{case.id}] input values must not be empty")
        try:
            normalized = output_model.model_validate(case.expected).model_dump(mode="json")
        except ValidationError as exc:
            problems.append(f"[{case.id}] expected: {_errors(exc)}")
            continue
        cases.append(case.model_copy(update={"expected": normalized}))

    if problems:
        listing = "\n".join(f"  - {p}" for p in problems)
        raise DataValidationError(
            f"Dataset {manifest.name}@{manifest.version} has {len(problems)} problem(s):\n{listing}"
        )
    return Dataset(manifest=manifest, cases=tuple(cases))

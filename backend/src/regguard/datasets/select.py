"""Deterministic case selection: filters and label-stratified subsets (for rate-limited runs)."""

import random
from collections import defaultdict
from collections.abc import Sequence

from regguard.core.errors import DataValidationError
from regguard.datasets.models import GoldenCase


def select_cases(
    cases: Sequence[GoldenCase],
    *,
    ids: Sequence[str] | None = None,
    tags: Sequence[str] | None = None,
    limit: int | None = None,
    label_field: str | None = None,
    seed: int = 0,
) -> tuple[GoldenCase, ...]:
    """Filter by ids/tags, then take a stratified, seed-deterministic subset of ``limit`` cases.

    The result keeps the dataset's original order so runs are easy to compare.
    """
    selected = list(cases)
    if ids:
        known = {c.id for c in selected}
        unknown = sorted(set(ids) - known)
        if unknown:
            raise DataValidationError(f"Unknown case ids: {', '.join(unknown)}")
        wanted = set(ids)
        selected = [c for c in selected if c.id in wanted]
    if tags:
        wanted_tags = set(tags)
        selected = [c for c in selected if wanted_tags.intersection(c.tags)]
    if limit is not None:
        if limit < 1:
            raise DataValidationError("limit must be >= 1")
        if limit < len(selected):
            selected = _stratified(selected, limit, label_field, seed)
    return tuple(selected)


def _stratified(
    cases: list[GoldenCase], limit: int, label_field: str | None, seed: int
) -> list[GoldenCase]:
    rng = random.Random(seed)  # noqa: S311 - sampling, not security
    groups: dict[str, list[GoldenCase]] = defaultdict(list)
    for case in cases:
        key = str(case.expected.get(label_field)) if label_field else ""
        groups[key].append(case)
    queues = []
    for key in sorted(groups):
        group = groups[key][:]
        rng.shuffle(group)
        queues.append(group)

    chosen: set[str] = set()
    while len(chosen) < limit:  # round-robin across labels keeps the balance
        for queue in queues:
            if queue and len(chosen) < limit:
                chosen.add(queue.pop().id)
    return [c for c in cases if c.id in chosen]

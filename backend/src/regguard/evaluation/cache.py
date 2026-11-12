"""On-disk response cache keyed by the exact request.

Modes:
- ``read-write`` (default): reuse identical past responses, store new ones.
- ``refresh``: always call the provider, but store the fresh response.
- ``off``: neither read nor write.

A cache hit cannot reveal a provider silently changing its model, so drift-monitoring
runs must use ``refresh``. Cached responses are flagged and excluded from latency stats.
"""

import contextlib
import hashlib
import json
import os
from enum import StrEnum
from pathlib import Path

from pydantic import ValidationError

from regguard.core.types import Completion
from regguard.providers.base import CompletionRequest


class CacheMode(StrEnum):
    READ_WRITE = "read-write"
    REFRESH = "refresh"
    OFF = "off"


class ResponseCache:
    def __init__(self, directory: Path, mode: CacheMode, *, namespace: str) -> None:
        self.directory = directory
        self.mode = mode
        self.namespace = namespace  # provider + endpoint: never mix responses across providers

    def key(self, request: CompletionRequest, sample_idx: int = 0) -> str:
        payload = {
            "ns": self.namespace,
            "request": request.model_dump(mode="json"),
            "sample": sample_idx,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.directory / key[:2] / f"{key}.json"

    def contains(self, key: str) -> bool:
        return self.mode is CacheMode.READ_WRITE and self._path(key).is_file()

    def get(self, key: str) -> Completion | None:
        if self.mode is not CacheMode.READ_WRITE:
            return None
        path = self._path(key)
        try:
            completion = Completion.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError):
            return None  # missing or corrupt entry: treat as a miss
        return completion.model_copy(update={"cached": True})

    def put(self, key: str, completion: Completion) -> None:
        if self.mode is CacheMode.OFF:
            return
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(completion.model_dump_json(), encoding="utf-8")
        try:
            os.replace(tmp, path)  # atomic: readers never see a half-written file
        except OSError:
            with contextlib.suppress(OSError):
                tmp.unlink()

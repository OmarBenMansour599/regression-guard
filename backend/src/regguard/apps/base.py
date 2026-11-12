"""An *application under test*: its inputs and the structured output it must produce.

Adding a new LLM application = a new module with an ``AppSpec`` + a registry entry.
The evaluation engine never needs to know about specific applications.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from regguard.core.errors import DataValidationError

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class AppSpec:
    name: str
    output_model: type[BaseModel]
    input_variables: tuple[str, ...]
    mock_response: str  # valid example output, used by the offline mock provider


def extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from model text: plain, inside ``` fences, or wrapped in prose."""
    candidate = text.strip()
    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        # Fallback: a JSON object wrapped in prose ("Sure! {...} Thanks.").
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            raise DataValidationError("no JSON object found in output") from exc
        try:
            data = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as inner:
            raise DataValidationError(f"output is not valid JSON: {inner.msg}") from inner
    if not isinstance(data, dict):
        raise DataValidationError("output JSON must be an object")
    return data


def parse_output(text: str, spec: AppSpec) -> BaseModel:
    data = extract_json(text)
    try:
        return spec.output_model.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()
        )
        raise DataValidationError(f"output does not match schema: {problems}") from exc

"""Versioned prompt configuration.

The prompt file is the "code" RegressionGuard runs CI against: system text, user template,
few-shot examples, and the model + parameters. Templates use ``$name`` placeholders
(``string.Template``) so JSON braces in prompts need no escaping; write ``$$`` for a literal ``$``.
"""

import hashlib
import json
from datetime import date
from string import Template
from typing import Any, Self

from pydantic import Field, model_validator

from regguard.core.types import FrozenModel

# Fields that change model behavior. Descriptive metadata is excluded from the hash so
# that editing a comment or date does not look like a prompt change.
_HASHED_FIELDS = {"system", "user_template", "input_variables", "few_shot", "model"}


class ModelParams(FrozenModel):
    model: str
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=300, gt=0)
    seed: int | None = 42
    json_mode: bool = True
    extra: dict[str, Any] = Field(default_factory=dict)


class FewShotExample(FrozenModel):
    input: dict[str, str]
    output: str


class PromptConfig(FrozenModel):
    id: str = Field(min_length=1)
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    description: str = ""
    created_at: date | None = None
    model: ModelParams
    system: str = Field(min_length=1)
    user_template: str = Field(min_length=1)
    input_variables: tuple[str, ...] = Field(min_length=1)
    few_shot: tuple[FewShotExample, ...] = ()

    @model_validator(mode="after")
    def _check_variables(self) -> Self:
        template = Template(self.user_template)
        if not template.is_valid():
            raise ValueError("user_template has an invalid placeholder (use $name or ${name})")
        used = set(template.get_identifiers())
        declared = set(self.input_variables)
        if used != declared:
            raise ValueError(
                f"user_template placeholders {sorted(used)} do not match "
                f"input_variables {sorted(declared)}"
            )
        for i, example in enumerate(self.few_shot):
            if set(example.input) != declared:
                raise ValueError(f"few_shot[{i}] inputs must be exactly {sorted(declared)}")
        return self

    @property
    def content_hash(self) -> str:
        """Stable SHA-256 of the behavior-relevant content."""
        data = self.model_dump(mode="json", include=_HASHED_FIELDS)
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

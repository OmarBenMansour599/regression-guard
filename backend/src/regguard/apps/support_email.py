"""Customer-support email classifier: category + one-sentence summary."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from regguard.apps.base import AppSpec

Category = Literal["billing", "technical", "account", "general"]
CATEGORIES: tuple[str, ...] = ("billing", "technical", "account", "general")


class SupportEmailOutput(BaseModel):
    # Strict on purpose: extra keys or a wrong category spelling are structural regressions.
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: Category
    summary: str = Field(min_length=1, max_length=300)

    @field_validator("summary")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


SPEC = AppSpec(
    name="support_email_classifier",
    output_model=SupportEmailOutput,
    input_variables=("email",),
    mock_response='{"category": "billing", "summary": "Customer reports a duplicate charge."}',
    label_field="category",
    summary_field="summary",
)

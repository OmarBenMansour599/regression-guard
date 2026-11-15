"""LLM-judge output: schema, parsing and conversion to a metric score. Pure (no I/O).

The judge model's answer is untrusted text like any other model output: it must parse as
``{"score": 1-5, "reason": "..."}`` or it is rejected (and reported as a judge error,
never as a low quality score).
"""

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from regguard.apps.base import extract_json
from regguard.core.errors import DataValidationError
from regguard.core.types import MetricScore

JUDGE_METRIC = "summary_judge"
MIN_SCORE, MAX_SCORE = 1, 5
# Extra inputs a judge prompt receives on top of the app's own input variables.
REFERENCE_VAR = "reference_summary"
CANDIDATE_VAR = "candidate_summary"


class JudgeOutput(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    score: int = Field(ge=MIN_SCORE, le=MAX_SCORE)
    reason: str = Field(default="", max_length=1000)

    @field_validator("reason")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


def parse_judge_output(text: str) -> JudgeOutput:
    """Raises DataValidationError when the judge did not follow its output contract."""
    try:
        return JudgeOutput.model_validate(extract_json(text))
    except ValidationError as exc:
        problems = "; ".join(e["msg"] for e in exc.errors())
        raise DataValidationError(f"Invalid judge output: {problems}") from exc


def judge_metric_score(output: JudgeOutput) -> MetricScore:
    """Continuous, informational score (1-5). Whether it gates is decided by the gate config."""
    return MetricScore(
        name=JUDGE_METRIC,
        value=float(output.score),
        passed=None,
        detail={"reason": output.reason},
    )

"""LLM-as-judge: a second model grades the app's summary against the input and the reference.

The judge has its own versioned prompt and its own Executor (cache, retries, stats), which
shares the run's rate limiter because both use the same API key. A failed or unparseable
judge call is an infrastructure problem recorded on the case; it never lowers a quality score.
"""

from collections.abc import Mapping
from typing import Any

from regguard.core.errors import DataValidationError
from regguard.core.types import CaseError, JudgeResult
from regguard.datasets.models import GoldenCase
from regguard.evaluation.executor import Executor
from regguard.metrics.judge import CANDIDATE_VAR, REFERENCE_VAR, parse_judge_output
from regguard.prompts.models import PromptConfig
from regguard.prompts.render import build_request
from regguard.providers.base import CompletionRequest


def judge_request(
    prompt: PromptConfig, case: GoldenCase, output: Mapping[str, Any], summary_field: str
) -> CompletionRequest | None:
    """The judge call for one output, or None when there is nothing to judge."""
    reference = case.expected.get(summary_field)
    candidate = output.get(summary_field)
    if not isinstance(reference, str) or not isinstance(candidate, str) or not candidate.strip():
        return None
    inputs = {**case.input, REFERENCE_VAR: reference, CANDIDATE_VAR: candidate}
    return build_request(prompt, inputs)


class JudgeScorer:
    def __init__(self, prompt: PromptConfig, executor: Executor, summary_field: str) -> None:
        self.prompt = prompt
        self.executor = executor
        self.summary_field = summary_field

    def describe(self) -> dict[str, Any]:
        """Provenance stored in RunMeta.judge: enough to know which judge produced the scores."""
        return {
            "model": self.prompt.model.model,
            "prompt_id": self.prompt.id,
            "prompt_version": self.prompt.version,
            "prompt_hash": self.prompt.content_hash,
            "params": self.prompt.model.model_dump(mode="json", exclude={"model"}),
        }

    async def score(
        self, case: GoldenCase, output: Mapping[str, Any], *, sample_idx: int = 0
    ) -> JudgeResult | None:
        request = judge_request(self.prompt, case, output, self.summary_field)
        if request is None:
            return None
        outcome = await self.executor.call(request, sample_idx=sample_idx)
        if outcome.completion is None:
            return JudgeResult(model=request.model, error=outcome.error)
        completion = outcome.completion
        common: dict[str, Any] = {
            "model": completion.model,
            "latency_ms": completion.latency_ms,
            "usage": completion.usage,
            "cached": completion.cached,
        }
        try:
            parsed = parse_judge_output(completion.text)
        except DataValidationError as exc:
            error = CaseError(
                type="judge_invalid_output", message=f"{exc}: {completion.text[:200]}"
            )
            return JudgeResult(error=error, **common)
        return JudgeResult(score=parsed.score, reason=parsed.reason, **common)

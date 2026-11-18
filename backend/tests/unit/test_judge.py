"""LLM judge: output parsing, request building, runner integration, budget and CLI."""

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from regguard.apps.config import AppConfig, load_app_config
from regguard.apps.support_email import SPEC
from regguard.cli.main import EXIT_CONFIG_ERROR, app
from regguard.core.config import Settings
from regguard.core.errors import ConfigError, DataValidationError, ProviderError
from regguard.core.gating import GateConfig
from regguard.core.types import RunResult, RunStatus
from regguard.evaluation.judge import JudgeScorer, judge_request
from regguard.evaluation.runner import execute_run
from regguard.metrics.judge import JUDGE_METRIC, parse_judge_output
from regguard.prompts.loader import load_prompt_version
from regguard.providers.base import CompletionRequest
from regguard.providers.mock_provider import MockProvider
from regguard.services.run_service import (
    BudgetExceededError,
    RunOptions,
    check_budget,
    execute_prepared,
    load_judge_prompt,
    mock_responder,
    prepare_run,
)
from tests.conftest import EXAMPLE_APP
from tests.unit.test_datasets import balanced_cases, write_dataset
from tests.unit.test_runner import CASES, _executor, _plan
from tests.unit.test_runner import responder as app_responder

JUDGE_DIR = EXAMPLE_APP / "prompts" / "judge"
JUDGE = load_prompt_version(JUDGE_DIR, "v1")
JUDGE_MODEL = JUDGE.model.model
runner = CliRunner()


# --- parsing --------------------------------------------------------------------------------


def test_parse_valid_judge_output() -> None:
    out = parse_judge_output('{"reason": " Faithful and complete. ", "score": 5}')
    assert (out.score, out.reason) == (5, "Faithful and complete.")


def test_parse_accepts_fences_and_ignores_extra_keys() -> None:
    out = parse_judge_output('```json\n{"score": 3, "confidence": 0.9}\n```')
    assert (out.score, out.reason) == (3, "")


@pytest.mark.parametrize(
    "text",
    [
        '{"score": 0, "reason": "x"}',
        '{"score": 6, "reason": "x"}',
        '{"score": "4", "reason": "x"}',  # strict: a string is not a score
        '{"score": 4.5, "reason": "x"}',
        '{"reason": "no score"}',
        "I would give it a 4.",
        "[4]",
    ],
)
def test_parse_rejects_anything_off_contract(text: str) -> None:
    with pytest.raises(DataValidationError):
        parse_judge_output(text)


# --- request --------------------------------------------------------------------------------


def test_example_judge_prompt_is_valid_and_distinct_from_classifier() -> None:
    assert set(JUDGE.input_variables) == {"email", "reference_summary", "candidate_summary"}
    classifier = load_prompt_version(EXAMPLE_APP / "prompts" / "classify", "v1")
    assert classifier.model.model != JUDGE_MODEL  # different family: less self-preference


def test_judge_request_contains_email_reference_and_candidate() -> None:
    request = judge_request(
        JUDGE, CASES[0], {"summary": "Customer asks about a charge."}, "summary"
    )
    assert request is not None
    assert request.model == JUDGE_MODEL
    text = request.messages[-1].content
    assert "correct-billing" in text  # the email
    assert "Customer writes." in text  # the reference
    assert "Customer asks about a charge." in text  # the candidate


def test_nothing_to_judge_without_reference_or_candidate() -> None:
    no_reference = CASES[0].model_copy(update={"expected": {"category": "billing"}})
    assert judge_request(JUDGE, no_reference, {"summary": "x y z"}, "summary") is None
    assert judge_request(JUDGE, CASES[0], {"summary": "   "}, "summary") is None


# --- runner integration ---------------------------------------------------------------------


def routed(judge_answers: dict[str, str | Exception]) -> MockProvider:
    """App requests get the runner-test answers; judge requests are answered by case marker."""

    def respond(request: CompletionRequest) -> str | Exception:
        if request.model != JUDGE_MODEL:
            return app_responder(request)
        text = request.messages[-1].content
        for marker, answer in judge_answers.items():
            if marker in text:
                return answer
        return '{"reason": "ok", "score": 4}'

    return MockProvider(respond)


ANSWERS: dict[str, str | Exception] = {
    "correct-billing": '{"reason": "Faithful.", "score": 5}',
    "correct-technical": "The summary looks fine to me!",  # judge broke its own contract
    "wrong-label": '{"reason": "Wrong issue.", "score": 2}',
}


async def _judged_run(
    tmp_path: Path, answers: dict[str, str | Exception], max_error_rate: float = 0.5
) -> RunResult:
    provider = routed(answers)
    judge = JudgeScorer(JUDGE, _executor(tmp_path, provider), "summary")
    return await execute_run(
        _plan(),
        _executor(tmp_path, provider),
        run_id="r1",
        provider_name="mock",
        cache_mode="read-write",
        max_error_rate=max_error_rate,
        judge=judge,
    )


async def test_judge_scores_are_recorded_per_case(tmp_path: Path) -> None:
    result = await _judged_run(tmp_path, ANSWERS)
    by_id = {c.case_id: c for c in result.cases}

    c1 = by_id["c1"]
    assert c1.judge is not None
    assert (c1.judge.score, c1.judge.reason) == (5, "Faithful.")
    judge_score = next(s for s in c1.scores if s.name == JUDGE_METRIC)
    assert (judge_score.value, judge_score.passed) == (5.0, None)
    assert c1.passed  # the judge never decides pass/fail on its own

    c2 = by_id["c2"]  # unusable judge answer: an error on the judge, not a low score
    assert c2.judge is not None
    assert c2.judge.score is None
    assert c2.judge.error is not None
    assert c2.judge.error.type == "judge_invalid_output"
    assert JUDGE_METRIC not in {s.name for s in c2.scores}
    assert c2.passed

    assert by_id["c3"].judge is not None
    assert by_id["c3"].judge.score == 2  # type: ignore[union-attr]
    assert by_id["c4"].judge is None  # invalid app output: nothing to judge
    assert by_id["c5"].judge is None  # app call failed


async def test_judge_aggregates_and_provenance(tmp_path: Path) -> None:
    result = await _judged_run(tmp_path, ANSWERS)
    agg = result.aggregates
    assert agg[JUDGE_METRIC].n == 2
    assert agg[JUDGE_METRIC].value == pytest.approx(3.5)  # (5 + 2) / 2
    assert agg["judge_error_rate"].value == pytest.approx(1 / 3)
    assert agg["judge_tokens_total"].value > 0
    # App token accounting is untouched by the judge.
    app_tokens = sum(c.usage.total_tokens for c in result.cases if c.usage)
    assert agg["tokens_total"].value == app_tokens

    meta = result.meta
    assert meta.judge is not None
    assert meta.judge["model"] == JUDGE_MODEL
    assert meta.judge["prompt_hash"] == JUDGE.content_hash
    assert meta.execution.judge_api_calls == 3
    assert meta.execution.api_calls == 5
    assert result.status is RunStatus.COMPLETED  # 33% judge errors <= 50% limit


async def test_too_many_judge_errors_make_the_run_error_not_a_verdict(tmp_path: Path) -> None:
    result = await _judged_run(tmp_path, ANSWERS, max_error_rate=0.25)
    assert result.status is RunStatus.ERROR
    assert result.error is not None
    assert "judge error rate" in result.error


async def test_judge_provider_failure_keeps_the_case_scores(tmp_path: Path) -> None:
    down = ProviderError("judge down", retryable=False, status_code=400)
    result = await _judged_run(tmp_path, {"correct-billing": down})
    c1 = next(c for c in result.cases if c.case_id == "c1")
    assert c1.judge is not None
    assert c1.judge.error is not None
    assert c1.judge.error.type == "client_error"
    assert c1.passed
    assert {s.name for s in c1.scores} >= {"schema_valid", "label_exact", "summary_format"}


async def test_judge_calls_are_cached_on_rerun(tmp_path: Path) -> None:
    await _judged_run(tmp_path, ANSWERS)
    second = await _judged_run(tmp_path, ANSWERS)
    assert second.meta.execution.judge_api_calls == 0
    assert second.meta.execution.judge_cache_hits == 3
    assert second.aggregates[JUDGE_METRIC].value == pytest.approx(3.5)


def test_judge_gate_default_is_report_only() -> None:
    threshold = GateConfig().threshold_for(JUDGE_METRIC)
    assert threshold is not None
    assert threshold.gating is False
    assert threshold.epsilon == 0.5


# --- service: config, budget ----------------------------------------------------------------


def _write_config(tmp_path: Path, judge: dict[str, object] | None) -> Path:
    write_dataset(tmp_path / "datasets", balanced_cases(per_category=3))
    data: dict[str, object] = {
        "name": "t",
        "app": "support_email_classifier",
        "prompts_dir": str(EXAMPLE_APP / "prompts" / "classify"),
        "datasets_dir": "datasets",
    }
    if judge is not None:
        data["judge"] = judge
    path = tmp_path / "regguard.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _config(tmp_path: Path) -> AppConfig:
    return load_app_config(_write_config(tmp_path, {"prompts_dir": str(JUDGE_DIR)}))


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_provider="mock",
        cache_dir=tmp_path / "cache",
        runs_dir=tmp_path / "runs",
        requests_per_minute=10_000,
    )


def test_example_config_uses_judge_v2() -> None:
    cfg = load_app_config(EXAMPLE_APP / "regguard.yaml")
    assert cfg.judge is not None
    assert cfg.judge.prompts_dir == JUDGE_DIR.resolve()
    assert load_judge_prompt(cfg, SPEC) == load_prompt_version(JUDGE_DIR, "v2")


def test_judge_v2_adds_the_personal_data_rule() -> None:
    v2 = load_prompt_version(JUDGE_DIR, "v2")
    assert v2.content_hash != JUDGE.content_hash
    assert v2.model == JUDGE.model  # same judge model: only the rubric changed
    assert "Personal data rule" in v2.system
    assert "AT MOST 3" in v2.system
    # Every few-shot answer follows the judge's own output contract.
    for example in v2.few_shot:
        parse_judge_output(example.output)
    assert any('"score": 3' in ex.output and "personal data" in ex.output for ex in v2.few_shot)


def test_disabled_judge_loads_nothing(tmp_path: Path) -> None:
    path = _write_config(tmp_path, {"prompts_dir": str(JUDGE_DIR), "enabled": False})
    assert load_judge_prompt(load_app_config(path), SPEC) is None


def test_judge_prompt_with_wrong_variables_is_a_config_error(tmp_path: Path) -> None:
    bad_dir = tmp_path / "judge"
    bad_dir.mkdir()
    prompt = yaml.safe_load((JUDGE_DIR / "v1.yaml").read_text(encoding="utf-8"))
    prompt["user_template"] = "Rate this: $candidate_summary"
    prompt["input_variables"] = ["candidate_summary"]
    prompt["few_shot"] = []
    (bad_dir / "v1.yaml").write_text(yaml.safe_dump(prompt), encoding="utf-8")
    cfg = load_app_config(_write_config(tmp_path, {"prompts_dir": str(bad_dir)}))
    with pytest.raises(ConfigError, match="must use exactly the variables"):
        load_judge_prompt(cfg, SPEC)


def test_budget_counts_judge_calls(tmp_path: Path) -> None:
    config, settings = _config(tmp_path), _settings(tmp_path)
    prepared = prepare_run(config, RunOptions(prompt_version="v1"), settings, provider_name="mock")
    assert prepared.judge_calls == 12
    assert prepared.uncached_calls == 24  # 12 app + 12 judge
    with pytest.raises(BudgetExceededError, match="--no-judge"):
        check_budget(
            prepare_run(
                config,
                RunOptions(prompt_version="v1", max_requests=20),
                settings,
                provider_name="mock",
            )
        )
    without = prepare_run(
        config, RunOptions(prompt_version="v1", judge=False), settings, provider_name="mock"
    )
    assert without.judge_prompt is None
    assert without.uncached_calls == 12


async def test_service_runs_judge_and_second_run_is_free(tmp_path: Path) -> None:
    config, settings = _config(tmp_path), _settings(tmp_path)
    options = RunOptions(prompt_version="v1")

    def provider() -> MockProvider:
        return MockProvider(mock_responder(SPEC, JUDGE))

    first = await execute_prepared(
        prepare_run(config, options, settings, provider_name="mock"), provider(), settings
    )
    assert first.status is RunStatus.COMPLETED
    assert first.meta.execution.api_calls == 12
    assert first.meta.execution.judge_api_calls == 12
    assert first.aggregates[JUDGE_METRIC].value == 4.0

    again = prepare_run(config, options, settings, provider_name="mock")
    assert (again.uncached_calls, again.judge_calls, again.uncached_judge_calls) == (0, 12, 0)
    second = await execute_prepared(again, provider(), settings)
    assert second.meta.execution.judge_api_calls == 0


# --- CLI ------------------------------------------------------------------------------------


@pytest.fixture
def judged_config(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("REGGUARD_LLM_PROVIDER", "mock")
    monkeypatch.setenv("REGGUARD_REQUESTS_PER_MINUTE", "10000")
    return str(_write_config(isolated_env, {"prompts_dir": str(JUDGE_DIR)}))


def test_cli_run_with_judge_then_show(judged_config: str) -> None:
    result = runner.invoke(app, ["run", "-p", "v1", "-c", judged_config])
    assert result.exit_code == 0, result.output
    assert "Judge:   up to 12 call(s), 0 cached" in result.output
    assert "judge 4/5" in result.output
    assert "summary_judge" in result.output
    assert "12 api, 0 cached, 0 retries   nvidia/" in result.output

    run_id = runner.invoke(app, ["runs", "list"]).stdout.split()[0]
    shown = runner.invoke(app, ["runs", "show", run_id, "--all"])
    assert shown.exit_code == 0, shown.output
    assert "judge:   Mock judge: offline run." in shown.output


def test_cli_no_judge_skips_it(judged_config: str) -> None:
    result = runner.invoke(app, ["run", "-p", "v1", "--no-judge", "-c", judged_config])
    assert result.exit_code == 0, result.output
    assert "Judge:" not in result.output
    assert "summary_judge" not in result.output


def test_cli_budget_message_mentions_no_judge(judged_config: str) -> None:
    result = runner.invoke(app, ["run", "-p", "v1", "--max-requests", "20", "-c", judged_config])
    assert result.exit_code == EXIT_CONFIG_ERROR
    assert "--no-judge" in result.output

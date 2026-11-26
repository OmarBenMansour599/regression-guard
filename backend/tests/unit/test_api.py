"""Phase 8 API: read-only routes over a seeded history database, and the local-only guards."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from regguard.api.app import create_app
from regguard.apps.config import AppConfig
from regguard.apps.registry import get_app
from regguard.cli.main import EXIT_CONFIG_ERROR
from regguard.cli.main import app as cli
from regguard.comparison.verdict import compare
from regguard.core.config import Settings
from regguard.core.gating import GateConfig
from regguard.core.types import BaselineFile, BaselineHeader, RunResult, RunStatus
from regguard.services.datasets import load_app_dataset
from regguard.services.history_service import history
from regguard.storage.baseline_store import save_baseline
from tests.conftest import EXAMPLE_APP
from tests.unit.run_factory import make_run, outcomes
from tests.unit.test_datasets import balanced_cases, write_dataset

T0 = datetime(2026, 11, 20, tzinfo=UTC)


def _run(run_id: str, day: int, fail: list[int], **kwargs: object) -> RunResult:
    run = make_run(outcomes(12, fail=fail), run_id=run_id, **kwargs)  # type: ignore[arg-type]
    meta = run.meta.model_copy(update={"started_at": T0 + timedelta(days=day)})
    return run.model_copy(update={"meta": meta})


@pytest.fixture
def setup(tmp_path: Path) -> tuple[AppConfig, Settings, str]:
    """App 't' with a 12-email dataset, baseline 'main' and 4 recorded runs."""
    write_dataset(tmp_path / "datasets", balanced_cases())
    config = AppConfig(
        name="t",
        app="support_email_classifier",
        prompts_dir=EXAMPLE_APP / "prompts" / "classify",
        datasets_dir=tmp_path / "datasets",
        baselines_dir=tmp_path / "baselines",
    )
    settings = Settings(
        llm_provider="mock",
        database_url=f"sqlite:///{(tmp_path / 'h.db').as_posix()}",
        runs_dir=tmp_path / "runs",
    )
    real_hash = load_app_dataset(config, get_app(config.app)).content_hash
    base = _run("r-base", 0, [], dataset_hash=real_hash)
    runs = [
        base,
        _run("r-v2", 1, [1, 2, 3, 4], prompt_version="v2", dataset_hash=real_hash),
        _run("r-v1-b", 2, [5], dataset_hash=real_hash),
        _run("r-err", 3, [1, 2, 3, 4, 5, 6], status=RunStatus.ERROR),
    ]
    header = BaselineHeader(
        name="main", app="t", source_run_id="r-base", promoted_at=T0, regguard_version="0"
    )
    save_baseline(config.baselines_dir, BaselineFile(header=header, run=base))
    with history(settings) as repo:
        for run in runs:
            repo.save_run(run)
        repo.save_comparison(compare(base, runs[1], GateConfig(), baseline_name="main"))
    return config, settings, real_hash


@pytest.fixture
def client(setup: tuple[AppConfig, Settings, str]) -> TestClient:
    config, settings, _ = setup
    return TestClient(create_app(config, settings), base_url="http://127.0.0.1")


# --- routes ------------------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["runs"] == 4 and body["app"] == "t"


def test_overview_reads_files_and_history(client: TestClient) -> None:
    body = client.get("/api/overview").json()
    assert {p["version"] for p in body["prompts"]} >= {"v1", "v2"}
    assert body["dataset"]["cases"] == 12
    assert body["dataset"]["labels"] == {"billing": 3, "technical": 3, "account": 3, "general": 3}
    [main] = body["baselines"]
    assert main["name"] == "main" and main["source_run_id"] == "r-base"
    assert body["recorded_prompt_versions"] == ["v1", "v2"]


def test_runs_page_with_filters_and_verdicts(client: TestClient) -> None:
    page = client.get("/api/runs").json()
    assert page["total"] == 4
    assert [r["run_id"] for r in page["items"]] == ["r-err", "r-v1-b", "r-v2", "r-base"]
    v2 = next(r for r in page["items"] if r["run_id"] == "r-v2")
    assert v2["verdict"] == "fail" and v2["verdict_baseline"] == "main"
    assert v2["metrics"]["schema_valid"] == 1.0  # headline metrics come from the database

    only_v2 = client.get("/api/runs", params={"prompt_version": "v2"}).json()
    assert [r["run_id"] for r in only_v2["items"]] == ["r-v2"] and only_v2["total"] == 1
    errors = client.get("/api/runs", params={"status": "error"}).json()
    assert [r["run_id"] for r in errors["items"]] == ["r-err"]
    second = client.get("/api/runs", params={"limit": 2, "offset": 2}).json()
    assert [r["run_id"] for r in second["items"]] == ["r-v2", "r-base"]
    assert client.get("/api/runs", params={"limit": 0}).status_code == 422
    assert client.get("/api/runs", params={"status": "bogus"}).status_code == 422


def test_run_detail_shows_emails_only_when_the_dataset_matches(client: TestClient) -> None:
    detail = client.get("/api/runs/r-v2").json()
    assert detail["run"]["meta"]["run_id"] == "r-v2"
    assert [c["verdict"] for c in detail["comparisons"]] == ["fail"]
    assert "test email number 1 " in detail["inputs"]["email-0001"]["email"]
    assert detail["expected"]["email-0001"]["category"] == "billing"

    other = client.get("/api/runs/r-err").json()  # fake dataset hash: changed since the run
    assert other["inputs"] == {} and "changed since this run" in other["notes"][0]


def test_compare_on_the_fly_saves_nothing(
    client: TestClient, setup: tuple[AppConfig, Settings, str]
) -> None:
    verdict = client.get("/api/compare", params={"candidate": "r-v1-b"}).json()
    assert verdict["verdict"] == "warn" and verdict["baseline_name"] == "main"
    against = client.get("/api/compare", params={"candidate": "r-v2", "against": "r-v1-b"}).json()
    assert against["baseline_run_id"] == "r-v1-b" and against["baseline_name"] is None
    _, settings, _ = setup
    with history(settings) as repo:
        assert repo.comparisons_for("r-v1-b") == []  # read-only: nothing stored


def test_trends_and_drift(client: TestClient) -> None:
    points = client.get("/api/trends", params={"metric": "schema_valid"}).json()
    assert [p["run_id"] for p in points] == ["r-base", "r-v2", "r-v1-b", "r-err"]  # oldest first
    v1 = client.get("/api/trends", params={"metric": "schema_valid", "prompt_version": "v1"})
    assert [p["prompt_version"] for p in v1.json()] == ["v1", "v1", "v1"]
    # each point says whether it is a real score: the ERROR run is flagged, n is the sample size
    assert [(p["status"], p["n"]) for p in points] == [
        ("completed", 12),
        ("completed", 12),
        ("completed", 12),
        ("error", 12),  # its failures are wrong labels, so all 12 outputs were scored
    ]
    drift = client.get("/api/drift").json()
    assert drift["baseline_name"] == "main" and drift["status"] == "insufficient"


def test_baseline_detail(client: TestClient) -> None:
    assert client.get("/api/baselines/main").json()["prompt_version"] == "v1"


@pytest.mark.parametrize(
    "path",
    [
        "/api/runs/nope",
        "/api/baselines/nope",
        "/api/compare?candidate=nope",
        "/api/compare?candidate=r-v2&baseline=nope",
        "/api/drift?baseline=nope",
        "/api/does-not-exist",
    ],
)
def test_missing_things_are_404(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 404 and response.json()["detail"]


def test_database_down_is_503_and_health_degrades(setup: tuple[AppConfig, Settings, str]) -> None:
    config, settings, _ = setup
    broken = settings.model_copy(update={"database_url": "nosuchdriver://x"})
    client = TestClient(create_app(config, broken), base_url="http://127.0.0.1")
    assert client.get("/api/runs").status_code == 503
    health = client.get("/api/health").json()
    assert health["status"] == "degraded" and health["database"] != "ok"
    assert client.get("/api/overview").status_code == 200  # files still readable


# --- security ----------------------------------------------------------------------------


def test_only_local_host_names_are_answered(setup: tuple[AppConfig, Settings, str]) -> None:
    """DNS rebinding: a page on evil.example resolving to 127.0.0.1 must get nothing."""
    config, settings, _ = setup
    app = create_app(config, settings)
    assert TestClient(app, base_url="http://localhost:8000").get("/api/health").status_code == 200
    evil = TestClient(app, base_url="http://evil.example").get("/api/runs")
    assert evil.status_code == 400 and "r-v2" not in evil.text


def test_read_only_no_cors_security_headers_no_docs(client: TestClient) -> None:
    for method in ("post", "put", "delete", "patch"):
        assert getattr(client, method)("/api/runs").status_code == 405
    response = client.get("/api/runs", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/docs").status_code != 200 or "swagger" not in client.get("/docs").text
    assert client.get("/api/openapi.json").json()["paths"]["/api/runs"]["get"]["operationId"] == (
        "listRuns"
    )


# --- dashboard files ---------------------------------------------------------------------


def test_serves_the_built_dashboard_with_client_side_routes(
    setup: tuple[AppConfig, Settings, str], tmp_path: Path
) -> None:
    config, settings, _ = setup
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<div id=root></div>", encoding="utf-8")
    (web / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (web / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    client = TestClient(create_app(config, settings, static_dir=web), base_url="http://127.0.0.1")
    assert client.get("/runs/r-v2").text == "<div id=root></div>"  # deep link -> app shell
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/favicon.svg").text == "<svg/>"
    # hashed build files are cached for good; the app shell is revalidated
    assert "immutable" in client.get("/assets/app.js").headers["cache-control"]
    assert client.get("/runs/r-v2").headers["cache-control"] == "no-cache"
    assert "outside" not in client.get("/..%2Fsecret.txt").text  # no path traversal
    assert client.get("/api/runs").status_code == 200  # API still wins over the app shell


def test_responses_are_compressed(client: TestClient) -> None:
    big = client.get("/api/runs/r-v2", headers={"Accept-Encoding": "gzip"})
    assert big.headers.get("content-encoding") == "gzip"
    assert big.json()["run"]["meta"]["run_id"] == "r-v2"  # still decodes fine
    small = client.get("/api/health", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in small.headers  # tiny bodies are not worth it


def test_without_a_built_dashboard_the_root_explains(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 404 and "Dashboard not built" in response.json()["detail"]


# --- CLI ---------------------------------------------------------------------------------


def test_serve_refuses_non_local_hosts() -> None:
    result = CliRunner().invoke(cli, ["serve", "--host", "0.0.0.0"])  # noqa: S104
    assert result.exit_code == EXIT_CONFIG_ERROR
    assert "local only" in result.output

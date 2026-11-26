"""FastAPI application: a thin HTTP shell over ``services.dashboard_service``.

Security (local tool that returns email text, ADR 0007):
- only GET routes: nothing can be changed through the API;
- the Host header must be 127.0.0.1 or localhost, so a web page cannot reach the API
  through DNS rebinding; no CORS headers, so other origins cannot read responses;
- strict security headers; FastAPI's /docs page is off (it loads scripts from a CDN).
"""

from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from starlette.datastructures import MutableHeaders
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from regguard import __version__
from regguard.apps.config import AppConfig
from regguard.core.config import Settings
from regguard.core.errors import ComparisonError, ConfigError, DataValidationError, NotFoundError
from regguard.core.types import Comparison, DriftReport, RunStatus
from regguard.services import dashboard_service as svc

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    # Charts set inline style attributes; scripts and everything else: same origin only.
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
}


def _cache_control(path: str) -> str:
    if path.startswith("/api/"):
        return "no-store"  # always fresh data
    if path.startswith("/assets/"):
        return "public, max-age=31536000, immutable"  # file names carry a content hash
    return "no-cache"  # index.html: pick up new builds


class HeadersMiddleware:
    """Security and cache headers, as plain ASGI.

    Not ``@app.middleware("http")``: that style raises "No response returned" when the
    browser cancels a request mid-way (seen in the browser tests).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        extra = [*SECURITY_HEADERS.items(), ("Cache-Control", _cache_control(scope["path"]))]

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in extra:
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _operation_id(route: APIRoute) -> str:
    """Stable, readable names for the generated TypeScript client (``listRuns``)."""
    head, *rest = route.name.split("_")
    return head + "".join(part.title() for part in rest)


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status)


def create_app(config: AppConfig, settings: Settings, *, static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(
        title="RegressionGuard",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
        generate_unique_id_function=_operation_id,
    )
    # Compress JS/CSS/JSON (the built dashboard is ~3x smaller). Added first = innermost.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

    app.add_middleware(HeadersMiddleware)

    @app.exception_handler(NotFoundError)
    async def not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        return _error(404, str(exc))

    @app.exception_handler(ComparisonError)
    async def not_comparable(request: Request, exc: ComparisonError) -> JSONResponse:
        return _error(409, str(exc))

    @app.exception_handler(DataValidationError)
    async def invalid_data(request: Request, exc: DataValidationError) -> JSONResponse:
        return _error(422, str(exc))

    @app.exception_handler(ConfigError)
    async def bad_config(request: Request, exc: ConfigError) -> JSONResponse:
        return _error(500, str(exc))

    async def database_down(request: Request, exc: Exception) -> JSONResponse:
        return _error(503, f"History database unavailable ({type(exc).__name__})")

    # OSError: unreadable SQLite file; ImportError: PostgreSQL URL without its driver.
    for error in (SQLAlchemyError, OSError, ImportError):
        app.add_exception_handler(error, database_down)

    @app.get("/api/health", tags=["meta"])
    def get_health() -> svc.HealthInfo:
        return svc.health(config, settings)

    @app.get("/api/overview", tags=["app"])
    def get_overview() -> svc.AppOverview:
        return svc.overview(config, settings)

    @app.get("/api/runs", tags=["runs"])
    def list_runs(
        limit: Annotated[int, Query(ge=1, le=svc.MAX_PAGE)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        prompt_version: str | None = None,
        status: RunStatus | None = None,
    ) -> svc.RunPage:
        return svc.list_runs(
            config,
            settings,
            limit=limit,
            offset=offset,
            prompt_version=prompt_version,
            status=status.value if status else None,
        )

    @app.get("/api/runs/{run_id}", tags=["runs"])
    def get_run(run_id: str) -> svc.RunDetail:
        return svc.run_detail(config, settings, run_id)

    @app.get("/api/baselines/{name}", tags=["app"])
    def get_baseline(name: str) -> svc.BaselineSummary:
        return svc.baseline_detail(config, name)

    @app.get("/api/compare", tags=["runs"])
    def compare_runs(
        candidate: str,
        baseline: str | None = "main",
        against: str | None = None,
        allow_dataset_change: bool = False,
    ) -> Comparison:
        return svc.compare_runs(
            config,
            settings,
            candidate,
            baseline=baseline,
            against=against,
            allow_dataset_change=allow_dataset_change,
        )

    @app.get("/api/trends", tags=["history"])
    def get_trend(
        metric: str,
        prompt_version: str | None = None,
        limit: Annotated[int, Query(ge=1, le=svc.MAX_TREND_POINTS)] = 100,
    ) -> list[svc.TrendPoint]:
        return svc.trend(config, settings, metric, prompt_version=prompt_version, limit=limit)

    @app.get("/api/drift", tags=["history"])
    def get_drift(baseline: str = "main") -> DriftReport:
        return svc.drift(config, settings, baseline=baseline)

    @app.get("/api/{rest:path}", include_in_schema=False)
    def unknown_api(rest: str) -> JSONResponse:
        return _error(404, f"Unknown API path: /api/{rest}")

    _mount_dashboard(app, static_dir)
    return app


def _mount_dashboard(app: FastAPI, static_dir: Path | None) -> None:
    """Serve the built single-page app; client-side routes get its index.html."""
    index = static_dir / "index.html" if static_dir is not None else None
    if static_dir is None or index is None or not index.is_file():

        @app.get("/", include_in_schema=False)
        def no_dashboard() -> JSONResponse:
            return _error(
                404, "Dashboard not built. The API is available under /api (see docs/dashboard.md)."
            )

        return

    if (static_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    root = static_dir.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def dashboard(path: str) -> FileResponse:
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)  # e.g. favicon.svg at the top level
        return FileResponse(index)

"""Drift check use case: a baseline from its file, the run history from the database."""

from regguard.apps.config import AppConfig
from regguard.comparison.drift import drift_report
from regguard.core.config import Settings
from regguard.core.types import DriftReport
from regguard.services.history_service import history
from regguard.storage.baseline_store import load_baseline


def check_drift(
    config: AppConfig, settings: Settings, *, baseline_name: str = "main"
) -> DriftReport:
    baseline = load_baseline(config.baselines_dir, baseline_name).run
    with history(settings) as repo:
        runs = repo.load_runs(app=config.name)
    return drift_report(baseline, runs, config.gate, baseline_name=baseline_name)

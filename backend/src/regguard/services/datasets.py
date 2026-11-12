"""Load an application's golden dataset (shared by CLI, evaluation runs and, later, the API)."""

from regguard.apps.base import AppSpec
from regguard.apps.config import AppConfig
from regguard.core.errors import ConfigError
from regguard.datasets.loader import load_dataset, resolve_version
from regguard.datasets.models import Dataset


def load_app_dataset(config: AppConfig, spec: AppSpec, version: str | None = None) -> Dataset:
    """Load ``version`` (default: latest) of the app's dataset, validated against its schema."""
    if config.datasets_dir is None:
        raise ConfigError(f"App '{config.name}' has no datasets_dir in regguard.yaml")
    resolved = resolve_version(config.datasets_dir, version)
    return load_dataset(
        config.datasets_dir / resolved,
        output_model=spec.output_model,
        input_variables=spec.input_variables,
    )

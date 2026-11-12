"""Which metrics an application is scored with. Phase 5 makes this configurable in regguard.yaml."""

from regguard.apps.base import AppSpec
from regguard.metrics.base import Metric
from regguard.metrics.deterministic import LabelExact, SchemaValid


def default_metrics(spec: AppSpec) -> list[Metric]:
    metrics: list[Metric] = [SchemaValid()]
    if spec.label_field:
        metrics.append(LabelExact(spec.label_field))
    return metrics

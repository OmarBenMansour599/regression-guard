"""Which metrics an application is scored with, derived from its AppSpec."""

from regguard.apps.base import AppSpec
from regguard.metrics.base import Metric
from regguard.metrics.deterministic import LabelExact, SchemaValid
from regguard.metrics.summary import SummaryFormat, SummarySimilarity


def default_metrics(spec: AppSpec) -> list[Metric]:
    metrics: list[Metric] = [SchemaValid()]
    if spec.label_field:
        metrics.append(LabelExact(spec.label_field))
    if spec.summary_field:
        metrics.append(SummaryFormat(spec.summary_field))
        metrics.append(SummarySimilarity(spec.summary_field))
    return metrics

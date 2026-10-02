"""Helpers shared by tests. Fixtures live in conftest.py."""

from dataclasses import dataclass

from opentelemetry.sdk.metrics.export import HistogramDataPoint, InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@dataclass(frozen=True)
class OTel:
    """In-memory sinks behind the process-wide OpenTelemetry providers."""

    spans: InMemorySpanExporter
    metrics: InMemoryMetricReader

    def histogram_points(self, name: str) -> list[HistogramDataPoint]:
        data = self.metrics.get_metrics_data()
        if data is None:
            return []
        return [
            point
            for resource in data.resource_metrics
            for scope in resource.scope_metrics
            for metric in scope.metrics
            if metric.name == name
            for point in metric.data.data_points
            if isinstance(point, HistogramDataPoint)
        ]

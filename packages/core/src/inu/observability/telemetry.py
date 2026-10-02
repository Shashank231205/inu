"""OpenTelemetry providers for traces and metrics.

Code anywhere in INU uses the OpenTelemetry API (`trace.get_tracer`,
`metrics.get_meter`). This module builds the SDK providers behind that API from
settings. The process entry point installs them once.
"""

from dataclasses import dataclass

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    MetricExporter,
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import (
    SERVICE_INSTANCE_ID,
    SERVICE_NAME,
    SERVICE_VERSION,
    Resource,
)
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

from inu import __version__
from inu.config import ExporterKind, MetricSettings, Settings, TraceSettings

DEPLOYMENT_ENVIRONMENT = "deployment.environment.name"


@dataclass(frozen=True)
class Telemetry:
    tracer_provider: TracerProvider
    meter_provider: MeterProvider

    def install(self) -> None:
        """Make these providers the process-wide defaults. Call once, at startup."""
        trace.set_tracer_provider(self.tracer_provider)
        metrics.set_meter_provider(self.meter_provider)

    def shutdown(self) -> None:
        """Flush pending spans and metrics. Call before the process exits."""
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()


def build_telemetry(
    settings: Settings,
    *,
    span_exporter: SpanExporter | None = None,
    metric_reader: MetricReader | None = None,
) -> Telemetry:
    """Build providers from settings. Explicit exporters/readers replace configured ones."""
    resource = Resource.create(
        {
            SERVICE_NAME: settings.telemetry.service_name,
            SERVICE_INSTANCE_ID: settings.instance_name,
            SERVICE_VERSION: __version__,
            DEPLOYMENT_ENVIRONMENT: settings.profile,
        }
    )

    traces = settings.telemetry.traces
    tracer_provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(traces.sample_ratio)),
    )
    processor = SimpleSpanProcessor(span_exporter) if span_exporter else _span_processor(traces)
    if processor:
        tracer_provider.add_span_processor(processor)

    readers = [metric_reader] if metric_reader else _metric_readers(settings.telemetry.metrics)
    meter_provider = MeterProvider(resource=resource, metric_readers=readers)

    return Telemetry(tracer_provider, meter_provider)


def _span_processor(settings: TraceSettings) -> SpanProcessor | None:
    match settings.exporter:
        case ExporterKind.NONE:
            return None
        case ExporterKind.CONSOLE:
            return SimpleSpanProcessor(ConsoleSpanExporter())
        case ExporterKind.OTLP:
            # Batching keeps network export off the latency-critical path.
            return BatchSpanProcessor(
                OTLPSpanExporter(endpoint=_otlp_url(settings.otlp_endpoint, "traces"))
            )


def _metric_readers(settings: MetricSettings) -> list[MetricReader]:
    exporter: MetricExporter
    match settings.exporter:
        case ExporterKind.NONE:
            return []
        case ExporterKind.CONSOLE:
            exporter = ConsoleMetricExporter()
        case ExporterKind.OTLP:
            exporter = OTLPMetricExporter(endpoint=_otlp_url(settings.otlp_endpoint, "metrics"))
    return [
        PeriodicExportingMetricReader(exporter, export_interval_millis=settings.export_interval_ms)
    ]


def _otlp_url(base: object, signal: str) -> str:
    # Validation guarantees an endpoint whenever the exporter is OTLP.
    return f"{str(base).rstrip('/')}/v1/{signal}"

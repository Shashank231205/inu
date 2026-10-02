import io
from pathlib import Path

import pytest
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, InMemoryMetricReader
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from inu import __version__
from inu.config import Settings, load_settings
from inu.observability import build_telemetry
from inu.observability import telemetry as telemetry_module


def settings_with(repo_config_dir: Path, monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return load_settings(profile="test", config_dir=repo_config_dir)


def test_resource_identifies_service_instance_version_and_profile(
    repo_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spans = InMemorySpanExporter()
    settings = settings_with(repo_config_dir, monkeypatch)
    telemetry = build_telemetry(settings, span_exporter=spans)

    telemetry.tracer_provider.get_tracer("t").start_span("s").end()

    (span,) = spans.get_finished_spans()
    assert (
        span.resource.attributes.items()
        >= {
            "service.name": "inu",
            "service.instance.id": "test",
            "service.version": __version__,
            "deployment.environment.name": "test",
        }.items()
    )


def test_sample_ratio_zero_drops_root_spans(
    repo_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spans = InMemorySpanExporter()
    settings = settings_with(repo_config_dir, monkeypatch, INU_TELEMETRY__TRACES__SAMPLE_RATIO="0")
    telemetry = build_telemetry(settings, span_exporter=spans)
    telemetry.tracer_provider.get_tracer("t").start_span("s").end()
    assert spans.get_finished_spans() == ()


def test_console_exporters_write_spans_and_metrics(
    repo_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_with(
        repo_config_dir,
        monkeypatch,
        INU_TELEMETRY__TRACES__EXPORTER="console",
        INU_TELEMETRY__METRICS__EXPORTER="console",
    )
    # The SDK binds sys.stdout at import time, before pytest captures it.
    buffer = io.StringIO()
    monkeypatch.setattr(
        telemetry_module, "ConsoleSpanExporter", lambda: ConsoleSpanExporter(out=buffer)
    )
    monkeypatch.setattr(
        telemetry_module, "ConsoleMetricExporter", lambda: ConsoleMetricExporter(out=buffer)
    )
    telemetry = build_telemetry(settings)
    telemetry.tracer_provider.get_tracer("t").start_span("console-span").end()
    telemetry.meter_provider.get_meter("t").create_counter("console.counter").add(1)
    telemetry.shutdown()

    out = buffer.getvalue()
    assert "console-span" in out
    assert "console.counter" in out


def test_otlp_exporters_target_the_signal_paths(
    repo_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_with(
        repo_config_dir,
        monkeypatch,
        INU_TELEMETRY__TRACES__EXPORTER="otlp",
        INU_TELEMETRY__TRACES__OTLP_ENDPOINT="http://collector:4318",
        INU_TELEMETRY__METRICS__EXPORTER="otlp",
        INU_TELEMETRY__METRICS__OTLP_ENDPOINT="http://collector:4318/",
    )
    endpoints: list[str] = []

    def fake_span_exporter(*, endpoint: str) -> InMemorySpanExporter:
        endpoints.append(endpoint)
        return InMemorySpanExporter()

    def fake_metric_exporter(*, endpoint: str) -> ConsoleMetricExporter:
        endpoints.append(endpoint)
        return ConsoleMetricExporter(out=io.StringIO())

    # Nothing listens on that host, so record the endpoints instead of exporting.
    monkeypatch.setattr(telemetry_module, "OTLPSpanExporter", fake_span_exporter)
    monkeypatch.setattr(telemetry_module, "OTLPMetricExporter", fake_metric_exporter)

    build_telemetry(settings).shutdown()

    assert endpoints == [
        "http://collector:4318/v1/traces",
        "http://collector:4318/v1/metrics",
    ]


def test_explicit_metric_reader_replaces_configured_ones(
    repo_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = InMemoryMetricReader()
    settings = settings_with(repo_config_dir, monkeypatch)
    telemetry = build_telemetry(settings, metric_reader=reader)
    telemetry.meter_provider.get_meter("t").create_counter("c").add(3)
    data = reader.get_metrics_data()
    assert data is not None
    (metric,) = data.resource_metrics[0].scope_metrics[0].metrics
    assert metric.name == "c"

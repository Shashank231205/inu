import os
from pathlib import Path

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from inu.config import load_settings
from inu.observability import build_telemetry
from support import OTel

REPO_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep the developer's own INU_* variables and .env out of every test."""
    for name in [n for n in os.environ if n.startswith("INU_")]:
        monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def repo_config_dir() -> Path:
    return REPO_CONFIG_DIR


@pytest.fixture(scope="session")
def _installed_otel() -> OTel:
    # OpenTelemetry allows one global provider per process, so install it once.
    settings = load_settings(profile="test", config_dir=REPO_CONFIG_DIR, environ={})
    spans, reader = InMemorySpanExporter(), InMemoryMetricReader()
    build_telemetry(settings, span_exporter=spans, metric_reader=reader).install()
    return OTel(spans, reader)


@pytest.fixture
def otel(_installed_otel: OTel) -> OTel:
    _installed_otel.spans.clear()
    return _installed_otel

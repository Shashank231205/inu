"""Logs, traces and metrics. See docs/observability.md."""

from inu.config import Settings
from inu.observability.logs import configure_logging
from inu.observability.telemetry import Telemetry, build_telemetry
from inu.observability.turns import stage, turn


def init_observability(settings: Settings) -> Telemetry:
    """Configure logging and install telemetry providers. Call once per process."""
    configure_logging(settings.log)
    telemetry = build_telemetry(settings)
    telemetry.install()
    return telemetry


__all__ = [
    "Telemetry",
    "build_telemetry",
    "configure_logging",
    "init_observability",
    "stage",
    "turn",
]

"""Structured logging.

structlog renders every record, including records from third-party libraries that
use the standard `logging` module, so the whole process emits one format. Each record
carries the current turn id and trace/span ids, which joins logs to traces.
"""

import logging
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any, TextIO

import structlog
from opentelemetry import trace
from pydantic import SecretStr
from structlog.typing import EventDict, Processor, WrappedLogger

from inu.config import LogFormat, LogSettings
from inu.errors import InuError

REDACTED = "**********"

# Marks INU's handler on the root logger, so reconfiguring replaces only our own.
_HANDLER_NAME = "inu"

# Matched against whole name segments ("api_key" -> {"api", "key"}), so counters such
# as "tokens_out" are not redacted while "auth_token" is.
SENSITIVE_SEGMENTS = frozenset(
    {"key", "apikey", "token", "secret", "password", "passwd", "authorization", "cookie"}
)


def redact_sensitive(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    return _redact(event_dict)


def add_trace_context(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event_dict["trace_id"] = format(context.trace_id, "032x")
        event_dict["span_id"] = format(context.span_id, "016x")
    return event_dict


def add_error_attributes(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    exc_info = event_dict.get("exc_info")
    error = sys.exc_info()[1] if exc_info is True else exc_info
    if isinstance(error, InuError):
        event_dict.update(error.attributes())
    return event_dict


def configure_logging(settings: LogSettings, *, stream: TextIO | None = None) -> None:
    """Route structlog and stdlib logging through one handler. Safe to call again."""
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_trace_context,
        add_error_attributes,
        redact_sensitive,
    ]
    output = stream or sys.stderr

    renderer: Processor
    if settings.format is LogFormat.JSON:
        final: list[Processor] = [structlog.processors.dict_tracebacks]
        renderer = structlog.processors.JSONRenderer()
    else:
        final = []
        renderer = structlog.dev.ConsoleRenderer(colors=output.isatty())

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # Reconfiguration must reach loggers that already exist.
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(output)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                *final,
                renderer,
            ],
        )
    )

    root = logging.getLogger()
    for existing in [h for h in root.handlers if h.get_name() == _HANDLER_NAME]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.level.value)


def _redact(mapping: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for name, value in mapping.items():
        if isinstance(value, SecretStr) or (value is not None and _is_sensitive(name)):
            mapping[name] = REDACTED
        elif isinstance(value, Mapping):
            mapping[name] = _redact(dict(value))
    return mapping


def _is_sensitive(name: str) -> bool:
    segments = name.lower().replace(".", "_").replace("-", "_").split("_")
    return any(segment in SENSITIVE_SEGMENTS for segment in segments)

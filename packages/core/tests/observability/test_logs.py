import io
import json
import logging
from typing import Any

import pytest
import structlog
from opentelemetry import trace
from pydantic import SecretStr

from inu.config import LogFormat, LogLevel, LogSettings
from inu.errors import ErrorCategory, InuError
from inu.observability import configure_logging
from inu.observability.logs import REDACTED


class ProviderDownError(InuError):
    code = "provider.unavailable"
    category = ErrorCategory.PROVIDER
    retryable = True


def call_provider() -> None:
    raise ProviderDownError("groq is down")


@pytest.fixture
def json_lines() -> io.StringIO:
    stream = io.StringIO()
    configure_logging(LogSettings(level=LogLevel.INFO, format=LogFormat.JSON), stream=stream)
    return stream


def records(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_json_record_has_core_fields(json_lines: io.StringIO) -> None:
    structlog.get_logger("inu.test").info("hello", answer=42)
    (record,) = records(json_lines)
    assert record["event"] == "hello"
    assert record["answer"] == 42
    assert record["level"] == "info"
    assert record["logger"] == "inu.test"
    assert record["timestamp"].endswith("Z")


def test_level_below_threshold_is_dropped(json_lines: io.StringIO) -> None:
    log = structlog.get_logger("inu.test")
    log.debug("hidden")
    log.warning("shown")
    assert [r["event"] for r in records(json_lines)] == ["shown"]


def test_stdlib_logging_from_libraries_uses_the_same_format(json_lines: io.StringIO) -> None:
    logging.getLogger("some.library").warning("from %s", "stdlib")
    (record,) = records(json_lines)
    assert record["event"] == "from stdlib"
    assert record["logger"] == "some.library"


def test_bound_context_is_merged(json_lines: io.StringIO) -> None:
    with structlog.contextvars.bound_contextvars(turn_id="t-1"):
        structlog.get_logger().info("inside")
    structlog.get_logger().info("outside")
    inside, outside = records(json_lines)
    assert inside["turn_id"] == "t-1"
    assert "turn_id" not in outside


def test_trace_and_span_ids_join_logs_to_traces(json_lines: io.StringIO) -> None:
    from opentelemetry.sdk.trace import TracerProvider

    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("work") as span:
        structlog.get_logger().info("traced")
    (record,) = records(json_lines)
    context = span.get_span_context()
    assert record["trace_id"] == format(context.trace_id, "032x")
    assert record["span_id"] == format(context.span_id, "016x")
    assert trace.get_current_span().get_span_context().is_valid is False


@pytest.mark.parametrize("name", ["api_key", "groq_api_key", "auth_token", "Authorization"])
def test_sensitive_names_are_redacted(json_lines: io.StringIO, name: str) -> None:
    structlog.get_logger().info("call", **{name: "s3cr3t"})
    (record,) = records(json_lines)
    assert record[name] == REDACTED


def test_redaction_reaches_nested_mappings_and_secret_values(json_lines: io.StringIO) -> None:
    structlog.get_logger().info(
        "call", headers={"x-api-key": "s3cr3t", "accept": "json"}, value=SecretStr("s3cr3t")
    )
    (record,) = records(json_lines)
    assert record["headers"] == {"x-api-key": REDACTED, "accept": "json"}
    assert record["value"] == REDACTED
    assert "s3cr3t" not in json_lines.getvalue()


@pytest.mark.parametrize("name", ["tokens_out", "max_tokens", "keyboard"])
def test_lookalike_names_are_not_redacted(json_lines: io.StringIO, name: str) -> None:
    structlog.get_logger().info("usage", **{name: 128})
    (record,) = records(json_lines)
    assert record[name] == 128


def test_inu_errors_add_taxonomy_fields_and_a_structured_traceback(
    json_lines: io.StringIO,
) -> None:
    try:
        call_provider()
    except ProviderDownError:
        structlog.get_logger().exception("llm.failed")
    (record,) = records(json_lines)
    assert record["error.code"] == "provider.unavailable"
    assert record["error.category"] == "provider"
    assert record["error.retryable"] is True
    assert record["exception"][0]["exc_type"] == "ProviderDownError"


def test_console_format_is_human_readable() -> None:
    stream = io.StringIO()
    configure_logging(LogSettings(level=LogLevel.DEBUG, format=LogFormat.CONSOLE), stream=stream)
    structlog.get_logger().debug("readable", turn="t-1")
    line = stream.getvalue()
    assert "readable" in line
    assert "turn" in line
    with pytest.raises(json.JSONDecodeError):
        json.loads(line)


def test_reconfiguring_replaces_only_our_handler() -> None:
    root = logging.getLogger()
    foreign = logging.NullHandler()
    root.addHandler(foreign)
    try:
        settings = LogSettings(level=LogLevel.INFO, format=LogFormat.JSON)
        configure_logging(settings, stream=io.StringIO())
        configure_logging(settings, stream=io.StringIO())
        ours = [h for h in root.handlers if h.get_name() == "inu"]
        assert len(ours) == 1
        assert foreign in root.handlers
    finally:
        root.removeHandler(foreign)

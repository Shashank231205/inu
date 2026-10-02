"""Turn and stage instrumentation.

A *turn* is one exchange, from the user's input to INU's finished reply. Each turn is
a root span with a turn id. Every piece of work inside it (speech-to-text, routing,
the model call, text-to-speech) is a *stage*, recorded as a child span and as a
duration histogram labelled by stage and outcome. Those histograms are what the
latency budget (NFR-1) is measured against.
"""

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import structlog
from opentelemetry import metrics, trace
from opentelemetry.trace import Span, Status, StatusCode

from inu.errors import InuError

# OpenTelemetry's own alias is a chained assignment that type checkers can't use.
type AttributeValue = str | bool | int | float

TURN_ID = "inu.turn.id"
STAGE = "inu.stage"
OUTCOME = "inu.outcome"
OUTCOME_OK = "ok"

_tracer = trace.get_tracer("inu")
_meter = metrics.get_meter("inu")
_turn_duration = _meter.create_histogram(
    "inu.turn.duration", unit="ms", description="Wall time of a whole turn"
)
_stage_duration = _meter.create_histogram(
    "inu.stage.duration", unit="ms", description="Wall time of one stage of a turn"
)


@contextmanager
def turn(turn_id: str | None = None) -> Iterator[str]:
    """Run a turn. Yields the turn id, which logs inside the block carry automatically."""
    tid = turn_id or uuid.uuid4().hex
    with (
        structlog.contextvars.bound_contextvars(turn_id=tid),
        _timed_span("turn", {TURN_ID: tid}, _turn_duration, {}),
    ):
        yield tid


@contextmanager
def stage(name: str, **attributes: AttributeValue) -> Iterator[Span]:
    """Run one stage of the current turn as a child span, and record its duration."""
    with _timed_span(
        f"stage.{name}", {STAGE: name, **attributes}, _stage_duration, {STAGE: name}
    ) as span:
        yield span


@contextmanager
def _timed_span(
    name: str,
    attributes: dict[str, AttributeValue],
    histogram: metrics.Histogram,
    metric_attributes: dict[str, AttributeValue],
) -> Iterator[Span]:
    outcome = OUTCOME_OK
    started = time.perf_counter_ns()
    with _tracer.start_as_current_span(name, attributes=attributes) as span:
        try:
            yield span
        except InuError as exc:
            outcome = exc.code
            span.set_attributes(exc.attributes())
            span.set_status(Status(StatusCode.ERROR, exc.message))
            raise
        except BaseException as exc:
            outcome = type(exc).__name__
            raise
        finally:
            span.set_attribute(OUTCOME, outcome)
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
            histogram.record(elapsed_ms, {**metric_attributes, OUTCOME: outcome})

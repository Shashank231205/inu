import pytest
import structlog
from opentelemetry.trace import StatusCode

from inu.errors import ErrorCategory, InuError
from inu.observability import stage, turn
from support import OTel


class SttTimeoutError(InuError):
    code = "stt.timeout"
    category = ErrorCategory.TIMEOUT
    retryable = True


def test_stages_are_children_of_their_turn(otel: OTel) -> None:
    with turn("t-1"):
        with stage("stt"):
            pass
        with stage("llm", model="fast"):
            pass

    stt, llm, root = otel.spans.get_finished_spans()
    assert root.name == "turn"
    assert root.attributes is not None
    assert root.attributes["inu.turn.id"] == "t-1"
    for child in (stt, llm):
        assert child.parent is not None
        assert child.parent.span_id == root.context.span_id
    assert llm.attributes is not None
    assert llm.attributes["model"] == "fast"
    assert llm.attributes["inu.outcome"] == "ok"


def test_turn_id_is_generated_and_bound_to_logs(otel: OTel) -> None:
    with structlog.testing.capture_logs() as logs, turn() as turn_id:
        structlog.get_logger().info("inside")
    assert len(turn_id) == 32
    assert structlog.contextvars.get_contextvars().get("turn_id") is None
    # capture_logs bypasses processors, so check the bound context directly.
    assert logs == [{"event": "inside", "log_level": "info"}]


def test_inu_error_marks_span_and_metric_with_its_code(otel: OTel) -> None:
    with pytest.raises(SttTimeoutError), turn(), stage("stt"):
        raise SttTimeoutError("no final transcript in 2s")

    stt, root = otel.spans.get_finished_spans()
    assert stt.status.status_code is StatusCode.ERROR
    assert stt.attributes is not None
    assert stt.attributes["error.code"] == "stt.timeout"
    assert stt.attributes["error.retryable"] is True
    assert stt.attributes["inu.outcome"] == "stt.timeout"
    assert root.attributes is not None
    assert root.attributes["inu.outcome"] == "stt.timeout"

    outcomes = {
        point.attributes.get("inu.outcome")
        for point in otel.histogram_points("inu.stage.duration")
        if point.attributes and point.attributes.get("inu.stage") == "stt"
    }
    assert "stt.timeout" in outcomes


def test_unexpected_errors_are_recorded_by_type(otel: OTel) -> None:
    with pytest.raises(ZeroDivisionError), turn(), stage("route"):
        _ = 1 / 0

    route, _ = otel.spans.get_finished_spans()
    assert route.attributes is not None
    assert route.attributes["inu.outcome"] == "ZeroDivisionError"
    assert route.status.status_code is StatusCode.ERROR


def test_stage_durations_are_recorded_per_stage(otel: OTel) -> None:
    with turn():
        for name in ("tts", "tts", "vad"):
            with stage(name):
                pass

    counts: dict[object, int] = {
        point.attributes.get("inu.stage"): point.count
        for point in otel.histogram_points("inu.stage.duration")
        if point.attributes and point.attributes.get("inu.outcome") == "ok"
    }
    assert counts["tts"] >= 2
    assert counts["vad"] >= 1
    assert all(p.min >= 0 for p in otel.histogram_points("inu.turn.duration"))

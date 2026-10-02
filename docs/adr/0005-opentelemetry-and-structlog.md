# 0005. OpenTelemetry for traces and metrics, structlog for logs

- **Status:** accepted
- **Date:** 2026-10-02

## Context

The latency budget (NFR-1) is defined per stage, so the time spent in each stage of every turn has to be measured. Failures need grouping by cause, without parsing message text. INU runs on two machines and will later add agents and background jobs, so one request's activity has to be linkable across components.

## Decision

- **Traces and metrics:** the OpenTelemetry API everywhere in INU code. The SDK providers are built from settings and installed once per process.
- **Export:** OTLP over HTTP/protobuf to a collector, with spans batched off the hot path. Console and none exporters exist for development and tests.
- **Logs:** structlog, rendered as JSON (machines) or console (people). Standard-library logging from third-party packages goes through the same processors.
- **Correlation:** every log record carries `turn_id`, `trace_id` and `span_id`. Every stage records a span and a duration histogram, labelled by stage and outcome.
- **Errors:** an `InuError` taxonomy (code, category, retryable), recorded on spans, metrics and logs.

## Alternatives considered

| Option | Why not |
|---|---|
| `prometheus_client` for metrics plus a separate tracing library | Two instrumentation APIs; trace and metric attributes drift apart |
| OTLP over gRPC | Pulls in grpcio (large native wheels, slow ARM builds) with no benefit at INU's volume |
| OpenTelemetry logs signal | The Python logs SDK is less mature than structlog; trace ids in log records give the same correlation |
| Hosted observability free tiers | Third-party retention and quota limits; personal data in telemetry leaves the machines |
| Stdlib `logging` only | No structured context binding; JSON output needs custom formatters |

## Consequences

- OpenTelemetry allows one global provider per process, so tests install in-memory exporters once per session.
- The backend stack (collector, Tempo, Prometheus, Grafana) is a separate deliverable (Phase 3b) and needs Docker.
- Field-name redaction depends on a naming convention (`tokens_*` for counts), documented in [observability.md](../observability.md).

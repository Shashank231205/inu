# Observability

INU measures itself so that latency targets (NFR-1) and failures can be checked with data, not guessed. There are three signals, all joined by ids:

| Signal | Library | Joined by |
|---|---|---|
| Logs | structlog (stdlib `logging` is routed through it too) | `turn_id`, `trace_id`, `span_id` on every record |
| Traces | OpenTelemetry | the `turn` root span carries `inu.turn.id` |
| Metrics | OpenTelemetry | the `inu.stage` and `inu.outcome` attributes |

## Turns and stages

A **turn** is one exchange, from the user's input to INU's finished reply. A **stage** is one piece of work inside it.

```python
from inu.observability import stage, turn

with turn() as turn_id:
    with stage("stt"):
        transcript = await stt.finish()
    with stage("llm", provider="ollama", model=model_name):
        ...
```

Each turn produces:

- A trace: a `turn` root span with one `stage.<name>` child span per stage.
- Two histograms: `inu.turn.duration` and `inu.stage.duration` (ms), labelled with `inu.stage` and `inu.outcome`.
- Logs inside the block that automatically carry `turn_id` and the current trace and span ids.

**Outcomes:**

| What happened | `inu.outcome` value | Span status |
|---|---|---|
| Success | `ok` | unset |
| An `InuError` was raised | the error's `code`, e.g. `stt.timeout` | ERROR, plus `error.code`, `error.category` and `error.retryable` attributes |
| Any other exception | its type name | ERROR |

## Errors

Every error INU raises on purpose subclasses `inu.errors.InuError`, with:

- `code`: stable and dotted, e.g. `provider.unavailable`. Dashboards group by it.
- `category`: one of `config`, `validation`, `provider`, `timeout`, `rate_limited`, `cancelled`, `internal`.
- `retryable`: whether trying again could succeed. The resilience layer (Phase 13) relies on this.

## Redaction

Log fields are redacted when their name contains a sensitive segment:

- **Sensitive segments:** `key`, `token`, `secret`, `password`, `authorization`, `cookie`, and similar.
- **Matching:** whole segments only. `groq_api_key` and `auth_token` are redacted; `tokens_out` and `max_tokens` aren't.
- **Also redacted:** any `SecretStr` value, at any depth inside mappings.

Rule: name LLM usage counters `tokens_*`, not `token_*`.

## Configuration

```yaml
log:
  level: INFO            # DEBUG | INFO | WARNING | ERROR | CRITICAL
  format: json           # json | console
telemetry:
  service_name: inu
  traces:
    exporter: none       # none | console | otlp
    otlp_endpoint: http://localhost:4318   # required for otlp
    sample_ratio: 1.0    # applied to root spans; children follow their parent
  metrics:
    exporter: none
    export_interval_ms: 10000
```

OTLP uses HTTP/protobuf, sent to `<endpoint>/v1/traces` and `<endpoint>/v1/metrics`. Spans are batched, so exporting never sits on the voice loop's critical path.

## Checking the pipeline

```sh
INU_TELEMETRY__TRACES__EXPORTER=console uv run inu diag --profile laptop
```

This emits one synthetic turn with the stages `stt`, `route`, `llm` and `tts`, prints its spans, and finishes with the turn id.

## Backend stack (Phase 3b, pending)

An OpenTelemetry Collector feeding Grafana Tempo (traces), Prometheus (metrics) and Grafana (dashboards) will be added as a docker-compose stack once Docker is available. Application code won't change; only the exporter settings will.

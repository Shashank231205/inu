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

## Backend stack

Native Windows processes, no containers ([ADR 0007](adr/0007-native-observability-stack.md)):

| Component | Role | Address |
|---|---|---|
| Prometheus 3.15 | Metrics, received over OTLP; keeps exemplars (trace IDs on histogram samples) | http://127.0.0.1:9090 |
| Jaeger 2.21 | Traces, received over OTLP; in memory | UI http://127.0.0.1:16686, OTLP 4317 (gRPC) / 4318 (HTTP) |
| Grafana 13.2 | Dashboards, provisioned from `deploy/observability/grafana/` | http://127.0.0.1:3000 |

```powershell
uv run inu obs up        # first run downloads ~650 MB, verifies SHA-256, then starts all three
uv run inu obs status
uv run inu obs down
```

`obs up` prints the four `INU_TELEMETRY__*` variables to set in the shell that runs INU. Releases, ports and paths are in `deploy/observability/stack.yaml`; downloads resume if interrupted.

**Dashboards** (folder *INU* in Grafana):

- **Turn latency:** p50 and p95 per stage and for the whole turn, against the NFR-1 line, plus outcomes per stage. Exemplar dots on the latency graphs open the trace of that turn.
- **Audio health:** xruns by direction (input/output) and source (buffer/device), and stream recoveries.

**Metric names in Prometheus.** OTLP names are translated: dots become underscores and the unit becomes a suffix.

| OpenTelemetry | Prometheus |
|---|---|
| `inu.stage.duration` (ms) | `inu_stage_duration_milliseconds_bucket` / `_sum` / `_count`, labels `inu_stage`, `inu_outcome` |
| `inu.turn.duration` (ms) | `inu_turn_duration_milliseconds_*` |
| `inu.audio.xruns` | `inu_audio_xruns_total`, labels `direction`, `source` |
| `inu.audio.reconnects` | `inu_audio_reconnects_total` |
| resource `service.instance.id` | `instance` label (`laptop`, `vm`) |

**Known limits:**

- Grafana 13's Jaeger plugin still *searches* through Jaeger's removed `/api/traces`, so search traces in the Jaeger UI. Opening a trace by ID (exemplars, Explore) works in Grafana.
- One-shot commands export a single sample per process, which is not enough for `rate()`. Use `inu diag --turns 60 --interval-ms 250` to see the dashboards move.
- The OTel SDK's default histogram buckets (0, 5, 10, 25, 50, 75, 100, 250, 500, 750, 1000 ms, ...) are coarse below 25 ms. Latency-tuned buckets come with Phase 11.

**Checked on the laptop (2026-10-03):** a 60-turn `diag` run appeared as Jaeger traces (turn + 4 stage spans) and Prometheus histograms; every dashboard panel returned data through Grafana's query API, exemplars carried trace IDs that open in Jaeger, and a 10 s `inu audio bench` filled the audio dashboard (0 xruns).

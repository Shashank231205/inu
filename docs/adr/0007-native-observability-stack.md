# 0007. Native Windows observability stack: Prometheus, Jaeger and Grafana, no containers

- **Status:** accepted
- **Date:** 2026-10-02

## Context

ADR 0005 put OpenTelemetry in the code and left the backend for Phase 3b. The original plan was a docker-compose stack: an OpenTelemetry Collector, Grafana Tempo for traces, Prometheus for metrics, and Grafana for dashboards.

The owner's laptop runs no WSL, no Linux VM and no Docker Desktop. That is a firm decision, so containers are out on the development machine. The stack still has to:

- receive OTLP over HTTP from INU without code changes (ADR 0005),
- show one turn as a trace with its stage spans,
- keep the per-stage duration histograms that the latency budget (NFR-1) is measured against,
- start and stop with one command, and never require administrator rights,
- survive Windows Smart App Control, which blocks unsigned binaries it has not seen before.

## Decision

Run three upstream releases as plain Windows processes, managed by `inu obs up|down|status` (`packages/lab/src/inu_lab/obs.py`, config in `deploy/observability/`):

| Component | Release | Role | Listens on |
|---|---|---|---|
| Prometheus | 3.15.0 | Metrics, with its built-in OTLP receiver (`--web.enable-otlp-receiver`) | 127.0.0.1:9090 |
| Jaeger | 2.21.0 | Traces: OTLP in (gRPC and HTTP), in-memory store, query UI | 127.0.0.1:4317, 4318, 16686 |
| Grafana | 13.2.3 | Dashboards, with provisioned data sources and dashboards | 127.0.0.1:3000 |

- **No collector.** INU sends traces to Jaeger's OTLP endpoint and metrics to Prometheus's OTLP endpoint (`/api/v1/otlp/v1/metrics`). Both are just OTLP endpoints in INU's config, so a collector can be put back in front of them later without touching code.
- **Pinned and verified.** Each release is pinned by URL and SHA-256 (of the archive, or of the binary where upstream publishes only that) in `stack.yaml`. A mismatch deletes the download and stops.
- **Downloads resume.** The Grafana archive is 473 MB; on the owner's connection that takes about 30 minutes. Interrupted downloads continue from the `.part` file with an HTTP Range request (`inu.assets.fetch`).
- **Processes outlive the terminal.** Each component starts detached, breaking away from the terminal's job object when Windows allows it, with its PID and log under `data/tools/run/`. `down` and `status` check that a PID still belongs to the expected executable, so a recycled PID is never killed.
- **Loopback only.** Every port binds to 127.0.0.1. Grafana's anonymous access is safe because of that, and must not be copied to the VM.
- **Production is different.** The always-on VM (Linux ARM, Phase 30) runs the same three components; there, containers or system packages are fine. Only the endpoints in config change.

## Alternatives considered

| Option | Why not |
|---|---|
| docker-compose stack (the original plan) | Needs Docker Desktop, so WSL 2. The owner refuses both |
| OpenTelemetry Collector in front | One more process and config file, with nothing to do yet: no sampling, no fan-out. Easy to add later because INU only knows OTLP endpoints |
| Grafana Tempo for traces | Upstream ships no Windows binaries. Jaeger v2 does, and is built on the collector, so it accepts OTLP directly |
| Hosted free tiers (Grafana Cloud and others) | Traces and logs contain what the user said. They stay on the owner's machines |
| Run the stack on the Oracle VM only | Development would depend on the VM and Tailscale being up, and every span would cross the internet |

## Consequences

- **Measured on the laptop:** all three binaries ran under Smart App Control without being blocked. The end-to-end check is recorded in [observability.md](../observability.md#backend-stack).
- **Grafana cannot search Jaeger 2.21.** Jaeger removed its legacy `/api/traces` HTTP API. With the `jaegerEnableGrpcEndpoint` toggle, Grafana 13 uses Jaeger's `/api/v3` for health checks and trace-by-ID, but its search still calls the old path. So traces are reached from metrics instead: Prometheus stores exemplars (`--enable-feature=exemplar-storage`), and the Prometheus data source links their `trace_id` to Jaeger. Free-form search uses the Jaeger UI. Revisit when the plugin moves search to v3.
- **Two upstream quirks are handled in config:** Grafana needs its release root as `--homepath` (it does not resolve `bin/..`), and does not create its data directory.
- **Jaeger keeps traces in memory**, so they are lost on restart. Development only needs recent traces; the VM will use persistent storage.
- **Prometheus translates OTLP names:** `inu.stage.duration` in ms becomes `inu_stage_duration_milliseconds_*`, and dots in attribute names become underscores. Dashboards use the translated names.
- **Upgrades are a config change:** a new URL and hash in `stack.yaml`. Old versions stay on disk until deleted.

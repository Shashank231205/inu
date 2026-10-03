# INU roadmap and build playbook

The single source of truth for **what to build, how to build it, and where the project stands**. Anyone resuming work, after a break or with no other context, starts with [Where we stand](#where-we-stand).

Status: ✅ done · 🟨 in progress or partly done · ⬜ not started

---

## Where we stand

**Last updated:** 2026-10-02 (written just before a context compaction)

**Goal right now:** finish **Phase 3b** and **Phase 6** to 100%, then build **Phases 7 → 14** in order.

| | |
|---|---|
| Last commit | `30c16cb` feat(lab): add model bake-off harness. Phases 0, 1, 2 and 5 are ✅. |
| In progress | **3b** (native observability stack, code written, never run) and **6** (benchmarks running or finished). |
| Then | Phase 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14, following each phase's How steps below. |
| Blocked by owner | Phase 4's first CI run (needs the GitHub push; the owner said "push later"). Everything else in Phase 4 is done. |

### Resume checklist (do these in order)

**A. Check the state**
1. `cd C:\Users\91913\inu`, then `git status`. Expect **uncommitted 3b files**:
   - `packages/lab/src/inu_lab/obs.py`
   - `deploy/observability/**` (`stack.yaml`, `prometheus.yml`, `jaeger.yaml`, `grafana/provisioning/**`)
   - `packages/lab/pyproject.toml` (`obs` entry point, `psutil`), `pyproject.toml`/`uv.lock` (psutil, types-psutil)
   - `packages/lab/src/inu_lab/hf_login.py` + `packages/lab/tests/test_hf_login.py`
   - this file
2. Run `uv sync`, then `uv run poe check` (161 tests passed at the last green run, before `obs.py` existed).

**B. Phase 6: collect the benchmark results**

A background chain was started at about 21:00 on 2026-10-02:
1. `bench llm` (all 13 models)
2. `bench llm --models llama3.2:3b,granite4.1:3b,granite4.2:3b,phi4-mini,qwen3.5:4b,gemma4:e2b-it-qat --option num_gpu=99`
3. `bench stt` (LibriSpeech + Svarah; the HF login now works as Shashank2312)
4. `bench tts`

Results land in `benchmarks/results/<timestamp>-{llm,stt,tts}.json`. TTS audio is in `data/benchmarks/tts-samples/`.
- If any of those files are missing, rerun the missing steps with the same commands (`uv run inu --profile laptop bench …`). Run them **one at a time**: they skew each other.
- The TTS judge in `benchmarks/tts.yaml` is `whisper-small.en`. Switch it to the most accurate CPU STT engine from the STT results and rerun `bench tts` if it changes.
- Write **ADR 0008, model picks**, with tables. Pick:
  - the fast-tier LLM (speed + correct + guardrails + tools)
  - the deep-tier LLM
  - whether `num_gpu=99` beats the default placement
  - STT for the real-time path (CPU)
  - TTS engine and voice
- Write `docs/benchmarks/phase-06.md`: the full tables, plus how to rerun.
- Commit. Mark Phase 6 ✅.

**C. Phase 3b: native observability stack (no WSL, no Docker)**
1. `uv run inu --profile laptop obs up`. It downloads Prometheus 3.15.0, Jaeger 2.21.0 and Grafana 13.2.3 into `data/tools`, verifies their SHA-256 hashes, starts them, and prints the `$env:INU_TELEMETRY__…` lines.
   - If Windows Smart App Control blocks a binary, don't bypass it: report it to the owner.
2. Set those env vars, then run `uv run inu --profile laptop diag`.
3. Verify through the APIs:
   - **Jaeger:** `GET http://127.0.0.1:16686/api/traces?service=inu` shows the turn with `stt/route/llm/tts` spans.
   - **Prometheus:** `GET http://127.0.0.1:9090/api/v1/label/__name__/values` shows the real metric names (expected `inu_stage_duration_milliseconds_bucket` and similar; confirm them).
   - **Grafana:** `GET http://127.0.0.1:3000/api/health`.
4. Write the dashboards with the *confirmed* names into `deploy/observability/grafana/dashboards/`:
   - `turn-latency.json`: p50/p95 per `inu_stage`, turn duration, outcomes.
   - `audio-health.json`: xruns by direction/source, reconnects.
   Check them through `POST /api/ds/query` or by loading the dashboard JSON from `/api/dashboards/uid/...`.
5. Tests for `obs.py`, using fakes (no real downloads):
   - config load
   - `render()` templates
   - checksum mismatch
   - zip/tar extraction
   - `running_pid` rejecting a foreign PID
   - stop / start / status
   - the CLI
6. Docs:
   - Write **ADR 0007, native Windows observability stack** (the owner refuses WSL/Docker; Jaeger replaces Tempo; Prometheus' OTLP receiver replaces the collector).
   - Update the [observability.md](observability.md) section "Backend stack".
   - Commit. Mark Phase 3 ✅.
7. `uv run inu obs down` when finished.

**D. Then Phases 7–14.** Start each phase by reading its How and Done-when, and follow the [definition of done](#definition-of-done-for-every-phase). Use the Phase 6 picks. Phases 12–13 need a Groq API key: ask the owner to create one and add it with `uv run poe secrets-edit laptop`.

### Findings so far (Phase 6)

**Earlier run** (thin prompts, results deleted):

| Model | On GPU | First token | Speed | Notes |
|---|---|---|---|---|
| qwen3:1.7b | 100% | 29 ms | 117 tok/s | |
| qwen3.5:0.8b | 100% | 50 ms | 132 tok/s | Wrong maths |
| granite4.1 / 4.2 3b | 85–88% | 64–76 ms | ~57 tok/s | 100% tool calls |
| gemma4:e2b | 38% | 99 ms | 64 tok/s | 100% tool calls |
| qwen3.5:4b | 50% | 371 ms | 19 tok/s | |
| granite4.2:8b | | | ~9 tok/s | |
| qwen3.5:9b | | | ~7.5 tok/s | |

- **VRAM headroom:** Ollama keeps ~1 GiB of VRAM free (log: "free memory target 1024 MiB"; 3.2 GiB free of 4 GiB). That's why 3–4B models land partly on the CPU. Test `num_gpu=99`.
- **`lfm2.5:8b`** crashes llama-server on Windows (`0xc0000409`, lfm2moe architecture). Excluded.
- **`qwen3:4b`** ignores `think: false` and speaks its reasoning. Disqualified for voice.
- **The LLM benchmark** now uses `prompts/inu-system.md` and realistic multi-turn conversations, including long answers and guardrails (the owner asked for this; see `benchmarks/llm.yaml`).

### Waiting on the owner

| Decision or action | Blocks |
|---|---|
| GitHub repo public or private. **The owner said "push later": don't push until asked.** | Phase 4 first run, branch protection |
| Hinglish or English only (OQ-1) | Phase 6 STT/TTS picks, Phase 39 |
| Back up the age private key (`%APPDATA%\sops\age\keys.txt`) | Nothing, but losing it loses the secrets |
| Create accounts when needed: Groq, Kaggle, Modal, Oracle Cloud, Tailscale, Telegram | Phases 12, 30, 35 |

**Settled:**
- **No WSL, Linux or Docker on the laptop, ever** (the owner's decision). Dev services run natively on Windows. Linux-only services (Postgres + pgvector, Valkey) go on the Oracle VM over Tailscale, or use a native Windows alternative. Decide that in Phase 17's ADR.
- **Hugging Face:** logged in as Shashank2312 through `uv run python -m inu_lab.hf_login`. The plain `hf auth login` fails silently on this network.

### How to resume (general)

1. Read this section and the [working rules](#working-rules).
2. Follow the resume checklist above.
3. When a phase finishes, follow the [definition of done](#definition-of-done-for-every-phase) and **update this section**.

---

## Working rules

### Non-negotiables

- **No AI attribution anywhere:** not in commits, trailers, code, docs, PR text or the contributors list. Commits go out as `Shashank231205 <shashankshashi56233@gmail.com>`, set in the repo's local git config.
- **Never push** without the owner's explicit go-ahead.
- **Everything free.** Any free cloud service is allowed, but each one sits behind an adapter and its limits live in config.
- **Nothing hardcoded.** Defaults live in `config/base.yaml`; the code schema has no operational defaults.
- **Measure, don't guess.** Performance claims need numbers taken on the target laptop.
- **No AI slop:** clean, typed, tested code; comments explain *why*.

### Environment quirks on the owner's laptop

| Quirk | Handling |
|---|---|
| uv lives in `C:\Users\91913\.local\bin` | Prefix shell commands with `$env:Path = "C:\Users\91913\.local\bin;$env:Path"` if `uv` isn't found |
| HTTPS is intercepted (antivirus or proxy) | `UV_SYSTEM_CERTS=1` is set for the user. Python HTTP clients that use certifi fail; use `truststore`, or set `REQUESTS_CA_BUNDLE` to a PEM export of the Windows root store for that one command |
| Windows Smart App Control blocks unsigned, freshly built binaries (e.g. the gitleaks hook) | Prefer signed releases or pure-Python tools. Never try to bypass it. |
| SOPS / age installed by winget | `%LOCALAPPDATA%\Microsoft\WinGet\Packages\…`, on the user PATH in new shells |
| PowerShell 5.1 writes UTF-8 *with BOM* | Write files with the Write/Edit tools, or `ruff format` after any PowerShell write |
| mypy needs one run per package (each test dir has a `conftest.py`) | Always use `uv run poe typecheck`, never bare `mypy` |
| GPU | RTX 3050 Laptop, **4 GB VRAM**. CPU i7-11800H 8C/16T, 16 GB RAM. Ollama 0.34.3 installed. |
| Audio | Use WASAPI (laptop profile). Mic: Intel SST array. Speakers: Realtek. |
| No WSL / Docker / Linux | The owner's firm decision. Native Windows tools only; Linux services go on the VM. |
| Hugging Face login | `uv run python -m inu_lab.hf_login` (plain `hf auth login` can't verify the token through the HTTPS interception) |
| Long benchmarks | Run one at a time in the background. Others (or heavy work) running alongside skew the numbers. |

### Commands

```sh
uv run poe check                          # lint + strict types + tests (what CI runs)
uv run poe fmt                            # format and autofix
uv run inu --profile laptop config show
uv run poe config laptop                  # with SOPS secrets loaded (redacted)
uv run poe secrets-edit laptop
uv run inu --profile laptop audio devices
uv run inu --profile laptop audio bench --seconds 30 --cpu-load 0.8 [--gil-load]
INU_TEST_HARDWARE=1 uv run pytest packages/voice/tests/test_hardware.py
```

### Definition of done for every phase

1. Code with strict types and tests. Coverage stays ≥ 85%, and real hardware is tested where it matters.
2. A benchmark or measurement if the phase makes a performance claim. The numbers go in the ADR or docs.
3. An ADR in `docs/adr/` for every real decision, with the alternatives considered.
4. User-facing docs in `docs/`, and README status and links updated.
5. This file updated: the phase status, and **Where we stand**.
6. `uv run poe check` and `uv run pre-commit run --all-files` both green.
7. One Conventional Commit per phase (or sub-phase), with no attribution.

---

## Architecture in one picture

```
Mic ─► Voice gateway ──(events)──► Orchestrator ──► Router ─► local fast model (Ollama, GPU)
       wake, VAD, STT,             state machine     │       cloud chain (Groq → Gemini → OpenRouter)
       speaker ID, TTS,                              ├─► Tools / agents / MCP gateway
       barge-in                                      └─► Memory (Postgres + pgvector, event log)
Laptop = real-time reflex layer · Oracle free VM = always-on spine · Kaggle/Modal/Lightning = training
```

Details: [ADR 0002](adr/0002-hybrid-compute-topology.md).

## Dependency order

```
A Foundations → B Voice → C Brain → D Memory + event log ─┬─► E Tools → K MCP → J Agents → M Simulation lab
                                                           ├─► F Platform → H Iron Man layer → L Visual engine
                                                           └─► N Time machine (builds on D's event log)
G Model training runs in parallel from Phase 33, once real conversation data exists.
I Hardening runs last and repeats before every major release.
```

The event log is built in Stage D, so time travel works over the whole history.

---

## Stage A: Foundations

### 0. Vision, requirements, threat model ✅
- **Built:** [vision](vision.md); [requirements](requirements.md) with measurable targets; a STRIDE [threat model](threat-model.md); ADRs 0001–0002. Commit `48b3182`.

### 1. Monorepo and toolchain ✅
- **Built:**
  - uv workspace with `packages/*`
  - Poe tasks
  - ruff, mypy strict, pytest with an 85% coverage gate
  - pre-commit hooks: format, secrets, Conventional Commits
  - ADR 0003. Commit `64269a5`.

### 2. Config and secrets ✅
- **Built:**
  - pydantic-settings layers: `base.yaml` → profile → secrets dir → `.env` → `INU_*` env vars
  - Unknown keys are forbidden; settings objects are frozen.
  - SOPS/age-encrypted `secrets/<profile>.enc.env`, with hooks that reject plaintext
  - `inu config show|check`
  - ADR 0004, [configuration.md](configuration.md). Commit `51fa4c3`.

### 3. Observability ✅
- **3a, built:**
  - structlog with turn, trace and span ids on every record, plus redaction
  - OpenTelemetry traces and metrics; `turn()` / `stage()` helpers recording span + duration histograms
  - `InuError` taxonomy
  - `inu diag`
  - ADR 0005, [observability.md](observability.md). Commit `9b4e111`.
- **3b, built:** native Windows processes, no containers (the owner refuses WSL/Docker).
  - Prometheus 3.15 (OTLP receiver, exemplar storage), Jaeger 2.21 (OTLP in, in-memory), Grafana 13.2 with provisioned data sources and two dashboards (turn latency, audio health)
  - `inu obs up|down|status`: pinned, SHA-256-verified, resumable downloads; detached processes with PID checks
  - `inu diag --turns N`; `inu audio bench` exports its xrun counters
  - Verified on the laptop: traces in Jaeger, histograms and exemplars in Prometheus, every dashboard panel returns data. Grafana cannot *search* Jaeger 2.21 (plugin limitation); exemplars link metrics to traces instead.
  - ADR 0007, [observability.md](observability.md#backend-stack).

### 4. CI/CD 🟨
- **Built:**
  - `ci.yml`: hooks, tests on Ubuntu + Windows + Linux ARM (public repos), gitleaks, pip-audit
  - `release.yml`: tag → CI → version check → GitHub release
  - Dependabot with a 7-day cooldown; actions pinned to SHAs; actionlint and zizmor hooks
  - [ci.md](ci.md). Commit `e0fd8af`.
- **Remaining:**
  1. When the owner says so, create the repo and push.
  2. Watch the first run and fix anything that fails.
  3. Apply the branch protection listed in `ci.md`.
- **Done when:** CI is green on GitHub and `main` is protected.

---

## Stage B: Real-time voice

### 5. Audio I/O engine ✅
- **Built:**
  - `packages/voice` (`inu-voice`, laptop only)
  - WASAPI streams through a lock-free SPSC ring, consumer-side soxr LQ resampling, capture timestamps
  - Backpressured playback; `clear()` for barge-in within one block
  - Supervisor with reconnect, stall detection and default-device fallback
  - GIL switch interval set to 1 ms while running
  - `inu audio devices|bench`; CLI command plugins (`inu.commands` entry points)
  - ADR 0006, [audio.md](audio.md). Commit `0ce7aca`.
- **Results:** at 80% CPU plus GIL load for 30 s: 100% audio delivered, 0 dropouts, capture lag p50/p99 21.4/33.6 ms.

### 6. Model bake-off on the laptop 🟨 ← **current** (resume checklist B)
- **Goal:** choose the LLM, STT and TTS models with numbers from *this* GPU and CPU.
- **How:**
  1. **Research current candidates** that fit 4 GB VRAM. Model releases move fast, so check the Ollama library and Hugging Face at the time.
     - LLM, fast tier: 3–4B at Q4 (Qwen3-4B, Gemma-3-4B, Llama-3.2-3B, Phi-4-mini, and anything newer).
     - LLM, deep tier: an 8B with partial CPU offload.
     - STT: faster-whisper (base.en / small.en / distil / large-v3-turbo at int8), Moonshine, Parakeet-TDT (onnx-asr).
     - TTS: Kokoro-82M (kokoro-onnx), Piper, and anything newer.
  2. Create a dev-only package `packages/lab` (`inu-lab`) whose CLI plugin provides `inu bench llm|stt|tts|combined`. It writes raw JSON to `benchmarks/results/` and summaries to `docs/benchmarks/`. Call `truststore.inject_into_ssl()` before any Hugging Face download (HTTPS interception).
  3. **LLM:** use the Ollama streaming `/api/chat`.
     - **Measure:** cold load time; warm time to first token p50/p95; tokens/s; VRAM and GPU/CPU split (`nvidia-smi`, `ollama ps`).
     - **Sanity checks:** valid JSON tool calls, one-sentence instruction following.
  4. **STT:**
     - **Datasets:** a LibriSpeech test-clean subset, plus an Indian-accented English set (e.g. AI4Bharat Svarah) if it's available.
     - **Measure:** WER (jiwer with Whisper-style normalisation), latency for 2–5 s utterances, real-time factor, on CPU vs GPU.
  5. **TTS:**
     - **Measure:** time to first audio, real-time factor.
     - **Intelligibility:** round-trip WER (TTS → best STT).
  6. **Combined:** fast LLM on the GPU while STT/TTS run on the CPU at the same time, to measure contention (the real budget).
  7. Write ADR 0008 with the picks and [docs/benchmarks/phase-06.md](benchmarks/) with the tables. (ADR 0007 is the native observability stack from Phase 3b.)
- **Done when:** picks are recorded with numbers; the real-time path fits in ≤ 3.6 GB VRAM (NFR-3); a projected latency budget exists.

### 7. Streaming STT + VAD ⬜
- **How:**
  1. Define a `SpeechToText` protocol in core, with providers in `inu-voice`.
  2. **VAD:** Silero VAD (ONNX) on 16 kHz frames, re-windowed to the model's window size.
     - Hysteresis thresholds; minimum speech and silence durations from config.
     - End of speech = silence ≥ `endpoint_ms`. Tune it in the 200–400 ms range.
  3. **Streaming STT:** partial decodes on the growing utterance every ~300 ms (Whisper-style), or native streaming (Parakeet/Moonshine); final decode at the endpoint.
  4. Record `stage("vad")` and `stage("stt")` spans.
  5. Test with recorded WAV fixtures.
- **Done when:** the final transcript arrives ≤ 150 ms after end of speech (measured).

### 8. Streaming TTS ⬜
- **How:**
  1. Define a `TextToSpeech` protocol.
  2. **Sentence chunker:** splits on sentence ends and clauses, and handles abbreviations, numbers and decimals.
  3. Synthesize the first chunk immediately and stream chunks into `Speaker.play(final=False)`.
  4. **Phrase cache** of pre-rendered acknowledgements ("Yes?", "On it"). The disk key is text + voice + model version.
- **Done when:** first audio ≤ 120 ms after the first sentence is ready.

### 9. Voice pipeline + state machine ⬜
- **How:**
  1. An explicit transition table: IDLE → LISTENING → THINKING → SPEAKING (+ ERROR).
  2. One asyncio task per stage, joined by bounded queues.
  3. Push-to-talk or energy trigger until the wake word exists (Phase 40).
  4. A minimal Ollama client (the full provider layer comes in Phase 12).
  5. `inu voice run`, with a `turn()` span per exchange.
- **Done when:** spoken question → spoken answer end to end with the local model.

### 10. Barge-in and cancellation ⬜
- **How:**
  1. Keep VAD running during SPEAKING.
  2. **Echo control:** acoustic echo cancellation (WebRTC APM bindings or speexdsp), with a fallback of raising the VAD threshold while speaking.
  3. On user speech: `Speaker.clear()`, then cancel the LLM and TTS tasks through a task group.
- **Done when:** user speech → silence < 150 ms; INU never interrupts itself.

### 11. Latency engineering ⬜
- **How:**
  1. Per-stage budget table compared against traces.
  2. **Techniques:**
     - prompt-prefix KV reuse (stable system prompt, `keep_alive`)
     - speculative memory prefetch
     - TTS on the first clause
     - acknowledgement phrases on slow routes
  3. Revisit audio signalling vs polling, and audio in its own process ([ADR 0006](adr/0006-audio-io.md)).
  4. A scripted 100-turn benchmark with recorded audio.
- **Done when:** p95 end-of-speech → first audio < 900 ms (NFR-1), with a CI or nightly check against regressions.

---

## Stage C: Brain

### 12. LLM provider layer ⬜
- **How:**
  1. **`LLMProvider` protocol:** `stream(messages, tools, options) → AsyncIterator[Delta]`, with normalised `Message`, `ToolCall`, `Usage` and `FinishReason` types.
  2. **Adapters:** Ollama (native), OpenAI-compatible (covers Groq, OpenRouter, Cerebras), Gemini.
  3. **Transport:** httpx async with pooling and timeouts; structured output with JSON Schema; keys from secrets; system trust store for corporate TLS (make this a config option).
  4. **Tests:** contract tests on recorded HTTP (respx). Live smoke tests are opt-in only.
- **Done when:** switching provider is one line of config.

### 13. Resilience ⬜
- **How:**
  1. Retries with backoff + jitter, only for `retryable` errors.
  2. A circuit breaker per provider (closed / open / half-open; thresholds from config).
  3. **Quota tracker:** per-provider requests/min, requests/day and tokens/min from config, as token buckets. Switch providers *before* hitting a 429.
  4. **Fallback chain** from config:
     - Failure before the first token: transparent retry on the next provider.
     - Failure after tokens were spoken: a short spoken recovery, then continue.
  5. Fault-injection tests.
- **Done when:** killing a provider mid-conversation doesn't break the turn.

### 14. Router v1 ⬜
- **How:**
  1. **Features:** embedding similarity to labelled exemplars, length, code/reasoning cues, private-mode flag.
  2. **Routes:** local-fast / local-deep / cloud.
  3. **PII scrubber:** email, phone, Aadhaar/PAN patterns and known names, replaced with reversible placeholders.
  4. A labelled set of ≥ 200 requests.
- **Done when:** ≥ 90% routing accuracy; private mode verifiably sends nothing out.

### 15. Persona and prompt system ⬜
- **How:**
  1. A persona spec covering voice, brevity and form of address (configurable).
  2. Jinja2 templates in `prompts/`, versioned, with the version hash recorded on spans.
  3. Snapshot tests, plus a persona score (from Phase 33).
- **Done when:** the persona score is tracked per prompt version.

### 16. Dialog and context manager ⬜
- **How:**
  1. Token budget per model context.
  2. Assembly order: system → memories → rolling summary → recent turns.
  3. Reference resolution.
  4. A scripted 30-turn coherence test.
- **Done when:** 30-turn conversations stay coherent within budget.

---

## Stage D: Memory and data platform (no Docker on the laptop: Postgres runs on the VM or natively, decided in Phase 17's ADR)

### 17. Schema design and migrations ⬜
- **How:**
  1. Postgres 16 + pgvector in docker-compose (laptop dev and VM); SQLAlchemy 2 async (asyncpg) + Alembic.
  2. **Tables:**
     - conversations, turns
     - memories (embedding, importance, valid_from/valid_to)
     - facts, preferences
     - tool_calls, feedback
     - training_samples, datasets, model_versions, eval_runs
     - jobs, api_keys
     - **`events`**: append-only, with ULID, stream, type, jsonb payload, occurred_at and recorded_at. This is the time-machine foundation.
  3. An ER diagram in the docs; up/down migration tests with Testcontainers.
- **Done when:** migrations round-trip cleanly and every turn writes events.

### 18. Repositories and transactions ⬜
- **How:**
  1. A repository per aggregate; a Unit of Work giving one transaction per turn.
  2. Optimistic locking with a version column.
  3. Document the isolation-level choices.
  4. Concurrency tests.
- **Done when:** concurrent-writer tests pass.

### 19. Vector memory ⬜
- **How:**
  1. Embeddings through Ollama (pick in Phase 6 or here; e.g. nomic-embed-text, bge-m3) with an HNSW index.
  2. Hybrid search: Postgres full-text + vector, fused with reciprocal rank fusion; an optional small CPU reranker.
  3. A memory eval set.
- **Done when:** recall@5 ≥ 0.85.

### 20. Memory lifecycle ⬜
- **How:**
  1. **Write policy:** LLM-extracted candidates, importance scoring, similarity dedupe.
  2. Decay.
  3. **Contradictions:** the new fact supersedes the old one (valid_to set, link kept).
  4. Data classification for PII.
- **Done when:** contradiction tests pass ("moved to Pune" supersedes "lives in Bangalore").

### 21. Postgres job queue ⬜
- **How:**
  1. A `jobs` table read with `SELECT … FOR UPDATE SKIP LOCKED`.
  2. Leases with heartbeat; retries with backoff; dead-letter queue.
  3. Cron-style schedules; idempotency keys.
- **Done when:** 10k jobs, zero duplicates, zero lost.

### 22. Nightly consolidation ⬜
- **How:**
  1. A worker job on the VM reads the day's events and extracts facts, preferences and corrections.
  2. It writes memories and a daily summary.
- **Done when:** the next morning, INU knows yesterday (eval).

---

## Stage E: Tools

### 23. Tool framework ⬜
- **How:**
  1. **`Tool` protocol:** pydantic argument model → JSON Schema for the LLM; registry through entry points (like the CLI plugins).
  2. Permission tiers: safe / confirm / forbidden.
  3. Command pattern: execute / undo / audit event; timeouts.
  4. A voice confirmation flow.
- **Done when:** a new tool is one file with no core changes.

### 24. Core skills ⬜
- **Skills:**
  - app launch, file search
  - system stats (psutil)
  - timers, notes, clipboard, media keys
  - weather (Open-Meteo, free, no key)
  - web search through a free API or self-hosted SearXNG
- **The code runner waits for the Phase 67 sandbox.**
- **Done when:** the daily-use command set works by voice.

### 25. Integrations ⬜
- **How:**
  1. Google Calendar / Gmail through the OAuth desktop flow, read and draft only.
  2. GitHub, RSS news.
  3. Tokens encrypted at rest; refresh handled.
- **Done when:** "What's on today?" works.

### 26. Multi-step agent loop ⬜
- **How:** plan → act → observe, with a step budget, loop detection and human checkpoints. Tests use a scripted model.
- **Done when:** 5-step tasks complete reliably.

---

## Stage F: Platform and deployment

### 27. REST + WebSocket API ⬜
- **How:**
  1. FastAPI in `apps/api`, with `/v1` resources, OpenAPI, cursor pagination, idempotency keys, RFC 9457 errors and ETags.
  2. WebSocket for streaming turns and audio.
  3. Contract tests with Schemathesis.
- **Done when:** contract tests pass.

### 28. Auth and rate limiting ⬜
- **How:**
  1. Device API keys (argon2-hashed) plus short-lived JWTs.
  2. A Valkey token bucket through a Lua script, with per-route limits from config.
  3. Security headers.
  4. Load tests with k6 or locust.
- **Done when:** the load test shows the limits hold.

### 29. Caching layer ⬜
- **How:**
  1. L1 in-process TTL/LRU + L2 Valkey, cache-aside.
  2. Stampede protection: single-flight + jitter.
  3. Invalidation on write events; hit-rate metrics.
- **Done when:** there's a hit-rate dashboard and no stale-read bugs.

### 30. Always-on deployment ⬜
- **How:**
  1. **VM:** Oracle Always Free ARM (2 OCPU / 12 GB for new accounts), Ubuntu, docker compose (api, worker, postgres, valkey, observability).
  2. Tailscale, systemd.
  3. Zero-downtime redeploys.
  4. **Backups:** encrypted with age to Cloudflare R2's free tier, plus a restore-drill script.
  5. Deploy on tag through a GitHub Actions + Tailscale workflow.
- **Done when:** a restore from backup is proven in < 15 min (NFR-6).

### 31. Clients ⬜
- **How:**
  - Telegram bot.
  - Phone PWA (built with the HUD stack).
  - Laptop tray app.
  - An offline queue on the laptop that syncs to the VM.
- **Done when:** INU can be reached from the phone anywhere.

### 32. SLOs and alerting ⬜
- **How:**
  1. SLOs for latency and availability; error budgets.
  2. Grafana alerts sent to Telegram.
  3. k6 load tests; chaos drills (kill containers).
- **Done when:** an alert fires within 2 minutes of a failure.

---

## Stage G: Model training (free GPUs)

### 33. Eval harness ⬜ (built before any training)
- **How:**
  1. Suites in `evals/` (JSONL/YAML): tool-call accuracy, persona, memory recall, instruction following, safety, and subsets of IFEval, MMLU-Pro and GSM8K (lm-evaluation-harness) to catch forgetting.
  2. **Scorers:** exact, regex, JSON Schema, tool-call match, and LLM-as-judge with rubrics and position-bias control.
  3. Bootstrap confidence intervals.
  4. `inu eval run`; results stored and comparable.
- **Done when:** the baseline model has a scorecard with error bars.

### 34. Data engine ⬜
- **How:**
  1. Events → candidate samples, using signals: corrections, retries, task success, and spoken feedback.
  2. A review queue (dashboard or CLI).
  3. PII scrubbing; MinHash dedupe; quality filters.
  4. Versioned datasets in a private Hugging Face dataset repo, with data cards.
- **Done when:** a weekly dataset builds automatically.

### 35. Distillation + SFT ⬜
- **How:**
  1. **Teachers:** open-weight models (gpt-oss-120b, Qwen) on Groq's free tier generate answers and tool traces. **Only teachers whose license allows training on outputs; not Gemini.**
  2. **Training:** Unsloth QLoRA of the 4B student on Kaggle (P100 16 GB or 2×T4), tracked in MLflow on the VM.
  3. **Export:** GGUF Q4_K_M through llama.cpp, plus an Ollama Modelfile.
- **Done when:** the student beats its base on the INU suites.

### 36. Preference tuning ⬜
- **How:**
  - DPO/ORPO on correction pairs (chosen vs rejected); KTO on thumbs up/down (TRL).
  - Measure win-rate with a significance test.
- **Done when:** the preference win-rate improves with p < 0.05.

### 37. Continual learning ⬜
- **How:**
  - Weekly LoRA adapters, a replay buffer and a fixed mix ratio.
  - Merging with mergekit (TIES/DARE).
  - Forgetting curves on the general benchmarks.
- **Done when:** 8 weeks of updates with no general-benchmark regression.

### 38. Quantization and serving study ⬜
- **How:**
  - imatrix calibrated on INU's own data.
  - Compare Q4_K_M, Q5_K_M and IQ4_XS.
  - Speculative decoding with a small draft model (through a llama.cpp server adapter if Ollama lacks it).
  - A Pareto chart of quality vs latency.
- **Done when:** the best point on the Pareto curve ships.

### 39. STT finetune for the owner's voice ⬜
- **How:**
  1. `inu voice record` prompts sentences and stores WAV + text (2–5 hours).
  2. Whisper/Parakeet LoRA (PEFT) on Kaggle.
  3. WER per condition (quiet, fan, noisy); export to CTranslate2/ONNX.
- **Done when:** WER on the owner's voice drops ≥ 30%.

### 40. Wake word + speaker verification ⬜
- **How:**
  1. **Wake word:** an openWakeWord custom "INU" model, trained on synthetic TTS positives + negatives + the owner's recordings (Colab/Kaggle notebook); tuned on DET curves.
  2. **Speaker verification:** SpeechBrain ECAPA enrollment and thresholds.
- **Done when:** < 1 false wake per 10 h; > 95% detection; only the owner is answered.

### 41. Learned router ⬜
- **How:**
  - Logistic regression or LightGBM on logged routing features and outcomes (quality, latency, cost).
  - Offline eval → shadow → switch.
- **Done when:** it beats Router v1 on accuracy and latency.

### 42. MLOps automation ⬜
- **How:**
  1. A weekly GitHub Actions cron pushes a Kaggle kernel (dataset + script) through the Kaggle API, and polls it.
  2. Artifacts go to the HF Hub; evals run on Modal; a registry entry is made.
  3. Shadow mode on the laptop → canary → promote or roll back (CLI).
- **Done when:** weekly releases are fully hands-off.

### 43. Voice finetune (optional) ⬜
- **How:** StyleTTS2 / F5-TTS on a voice INU has rights to: the owner's or a consenting person's. **Never a celebrity's.**
- **Done when:** a blind A/B test prefers the new voice.

---

## Stage H: Iron Man layer

### 44. HUD dashboard ⬜
- **How:**
  1. A frontend ADR (likely React + Vite + TypeScript, with three.js later), served by the API.
  2. **Panels:** waveform, state, active tools, memory timeline, vitals, model scorecards.
  3. Live updates over WebSocket.
- **Done when:** it shows live data only and looks the part.

### 45. Proactive INU ⬜
- **How:**
  - Scheduler triggers: morning brief, reminders, anomaly alerts from metrics.
  - Quiet hours and a rate limit on proactive speech.
- **Done when:** INU speaks first, at the right times only.

### 46. Vision ⬜
- **How:**
  - Screenshot capture (mss) → Gemini's free vision API or a small local VLM.
  - Webcam presence detection (MediaPipe), opt-in.
- **Done when:** "What's this error?" works on the screen's contents.

### 47. Multi-device presence ⬜
- **How:** a device registry, active-device election, and a session handoff protocol.
- **Done when:** a conversation moves between laptop and phone seamlessly.

### 48. Tone awareness ⬜
- **How:** a small speech-emotion model plus text sentiment, adapting response length and pace.
- **Done when:** persona scores measurably improve.

---

## Stage I: Hardening

### 49. Security audit ⬜
- **How:**
  - A prompt-injection red-team suite (garak / promptfoo) against tools, the web and MCP.
  - Dependency and secret scans.
  - A threat model review and a pen-test checklist.

### 50. Performance pass ⬜
- **How:** profile with py-spy and traces, fix the top 3 bottlenecks, publish before/after numbers.

### 51. Docs and showcase ⬜
- **How:** architecture docs, ADR index, demo video, and blog posts (latency engineering, distillation results, STT finetune).

---

## Stage J: Multi-agent system

### 52. Agent runtime ⬜
- **How:**
  - An agent spec: role, tools, memory scope, budget, policy.
  - A supervisor/worker hierarchy.
  - A blackboard in Postgres; typed messages.
- **Done when:** the supervisor splits a task across 3 agents and merges the results.

### 53. Durable execution ⬜
- **How:** steps checkpointed as events; idempotent steps; sagas with compensation; resume after a crash.
- **Done when:** a power cut mid-task resumes correctly.

### 54. Human-in-the-loop ⬜
- **How:** approval requests by voice, Telegram or HUD; risk tiers; spend and quota budgets per task.
- **Done when:** nothing destructive happens without approval.

### 55. Agent observability ⬜
- **How:** trace trees per task (agent, tool, tokens, reason); replay a failed run with another model.
- **Done when:** any failure can be explained from its trace.

### 56. Agent evals ⬜
- **How:** task suites measuring success, steps, cost and time, with a gate before releasing a new agent version.
- **Done when:** every agent has a scorecard.

**Work agents** (plugins with evals): coder (Docker sandbox, opens PRs for review), researcher (cited reports), data analyst (SQL/pandas → HUD charts), job hunter, inbox/calendar (never sends without approval), meeting (transcribe → summary → actions), browser (Playwright, isolated profile), ops/INU-doctor.

---

## Stage K: MCP

### 57. INU as MCP client ⬜
- **How:** the official `mcp` Python SDK over stdio and streamable HTTP; servers declared in YAML; their tools wrapped into INU's tool registry.
- **Done when:** adding a server in YAML makes it usable immediately.

### 58. MCP gateway ⬜
- **How:**
  - Allowlists per server and tool; permission tiers; rate limits; audit log; output size caps.
  - Pin tool-description hashes and alert when they change.
- **Done when:** every external tool call passes through policy.

### 59. Tool retrieval at scale ⬜
- **How:** embed tool descriptions and pick the top-k per request; eval tool-selection accuracy.
- **Done when:** 300 tools connected and still under 1 s.

### 60. INU as MCP server ⬜
- **How:** expose memory search, notes and agents as MCP tools, with local auth.
- **Done when:** another AI tool can query INU's memory.

### 61. MCP security ⬜
- **How:** a red team for tool poisoning and injection in tool outputs; sandboxed server processes.
- **Done when:** the red-team suite passes.

---

## Stage L: Visual engine

### 62. Generative UI protocol ⬜
- **How:**
  - Typed scene specs (pydantic → JSON Schema) for chart, diagram, 3D, map, timeline and graph.
  - The LLM emits a spec through structured output; a validator runs with an auto-repair loop.
- **Done when:** specs validate, and invalid ones get repaired.

### 63. Renderers ⬜
- **How:** ECharts/Vega-Lite, Mermaid, three.js (react-three-fiber), MapLibre + OSM, KaTeX/function-plot, Cytoscape.
- **Done when:** every scene type renders at 60 fps.

### 64. Conversational visuals ⬜
- **How:** scene state kept server-side; voice edits become JSON Patch operations.
- **Done when:** 10 follow-up edits on one visual work.

### 65. Gesture control ⬜
- **How:** MediaPipe Hands in the browser → gestures (pinch, rotate, zoom, swipe) → scene operations.
- **Done when:** a 3D model can be manipulated by hand.

### 66. AR mode ⬜
- **How:** WebXR on the phone with three.js and a scene anchor.
- **Done when:** a visual is anchored in the room.

---

## Stage M: Simulation lab

### 67. Sandboxed compute ⬜
- **How:**
  - Docker runner: no network, CPU/memory limits, non-root, read-only filesystem + tmpfs.
  - A SciPy-stack image; heavy jobs offloaded to Modal.
- **Done when:** generated code can't touch the host.

### 68. Model-building agent ⬜
- **How:**
  - Plan → write the model → state assumptions → run → validate (units with pint, known-case checks) → iterate.
  - Label every result: validated / approximate / speculative.
- **Done when:** results come with assumptions the owner can audit.

### 69. Simulation types ⬜
- **How:** ODE/physics, Monte Carlo, system dynamics, agent-based (Mesa), optimisation, graphs, finance; one eval case each.
- **Done when:** every type has a worked eval example.

### 70. Parameter exploration ⬜
- **How:** sweeps, sensitivity analysis (SALib), uncertainty bands, a live-updating 3D surface.
- **Done when:** a voice parameter change updates the visual live.

### 71. End-to-end demo ⬜
- **How:** a spoken idea → simulation → 3D visual → voice and gesture tweaks.
- **Done when:** there's a portfolio demo video.

---

## Stage N: Time machine

### 72. Event-sourced rebuild (CQRS) ⬜
- **How:** projections and read models rebuilt from the event log.
- **Done when:** full state can be rebuilt from events.

### 73. Bitemporal memory ⬜
- **How:** valid time + transaction time on facts; as-of queries.
- **Done when:** "What did INU believe on 1 March?" is answered exactly.

### 74. Replay, fork and compare ⬜
- **How:** deterministic replay from recorded inputs; fork with another model or prompt; diff the results.
- **Done when:** any past moment can be forked and compared.

### 75. Personal timeline ⬜
- **How:** a HUD timeline with voice queries ("show me my March").
- **Done when:** the timeline renders by voice.

### 76. Snapshots and undo ⬜
- **How:** memory and settings snapshots; compensating actions for undoable agent steps.
- **Done when:** "Undo everything from the last hour" works.

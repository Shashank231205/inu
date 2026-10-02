# Requirements

IDs are stable: tests, ADRs and issues refer to them. Each requirement is either testable or tied to a measurable target.

## Functional

### Voice
- **FR-V1** Detect the wake word "INU" continuously, without sending audio off the device.
- **FR-V2** Transcribe speech while the user is still talking (streaming), and finish within 150 ms of the end of speech.
- **FR-V3** Speak replies while they are still being generated, one sentence at a time.
- **FR-V4** Barge-in: if the user speaks while INU is talking, INU stops within 150 ms and listens.
- **FR-V5** Respond only to the enrolled owner's voice when speaker verification is on.
- **FR-V6** Text input is a first-class alternative to voice (CLI, phone, dashboard).

### Brain
- **FR-B1** Route each request to a local or cloud model based on intent, complexity and privacy mode.
- **FR-B2** When a provider fails or runs out of quota, fall back to the next one without the user noticing.
- **FR-B3** Private mode: nothing leaves the machine while it is on.
- **FR-B4** Remove personal details from any text sent to a cloud provider.
- **FR-B5** Keep a consistent persona, defined in versioned prompt files.

### Memory
- **FR-M1** Store every turn, tool call and memory change as an immutable event, from the very first release.
- **FR-M2** Recall relevant memories during a conversation using hybrid search (keyword and vector).
- **FR-M3** Consolidate each day's conversations overnight into facts, preferences and corrections.
- **FR-M4** Resolve contradictions: newer facts replace older ones, and the history is kept.
- **FR-M5** Bitemporal queries: answer "what did INU believe about X on date D".

### Tools and agents
- **FR-T1** New tools are plugins with schema-validated arguments. Adding one needs no core changes.
- **FR-T2** Every action has a permission tier: safe, needs confirmation, or forbidden.
- **FR-T3** Connect to external MCP servers through a policy gateway, and expose INU itself as an MCP server.
- **FR-T4** Long-running agent tasks survive crashes and restarts and resume from their last checkpoint.
- **FR-T5** Every tool call is logged with its inputs and outputs, and can be undone where possible.

### Visuals and simulation
- **FR-X1** Show a visual (chart, diagram, 3D scene, map, timeline) when it helps, or when asked.
- **FR-X2** A visual can be edited by voice ("rotate it", "only 2024") without being regenerated.
- **FR-X3** Run user-described simulations in a sandbox, state the assumptions, and label how far the result can be trusted.

### Learning
- **FR-L1** Build a training dataset every week from conversations and feedback.
- **FR-L2** Finetune on free cloud GPUs. Each run is reproducible and tracked.
- **FR-L3** Release a new model only if it passes the eval gate. Rollback takes one command.

## Non-functional

| ID | Requirement | Target | How it's measured |
|---|---|---|---|
| NFR-1 | End-of-speech → first audio | p50 < 700 ms, p95 < 900 ms | Per-turn traces; benchmark in CI |
| NFR-2 | Barge-in response | < 150 ms | Pipeline integration test |
| NFR-3 | VRAM use of the real-time path | ≤ 3.6 GB on a 4 GB GPU | Benchmark harness |
| NFR-4 | Always-on services uptime | 99% per month | Uptime probe |
| NFR-5 | Cost | ₹0 per month | Quota dashboard |
| NFR-6 | Recovery after data loss | Restore in < 15 min, lose < 24 h of data | Quarterly restore drill |
| NFR-7 | Security | No public endpoints; secrets encrypted at rest; every action audited | Threat model review; secret scanning in CI |
| NFR-8 | Code quality | `mypy --strict` clean; ≥ 85% line coverage on core | CI gates |
| NFR-9 | Configuration | No environment-specific values in code | Code review; startup validation |
| NFR-10 | Portability | Runs on Windows (laptop) and Linux ARM (VM) | CI matrix |

## Constraints

- Laptop: RTX 3050 Laptop GPU (4 GB VRAM), i7-11800H (8 cores, 16 threads), 16 GB RAM, Windows 11.
- Always-on server: Oracle Cloud Always Free, ARM, 2 OCPU and 12 GB RAM for new accounts.
- Training: Kaggle (30 GPU-hours/week), Modal ($30/month credit), Lightning AI (about 80 GPU-hours/month on interruptible machines).
- All usage must comply with each provider's terms: no Colab free tier as a server, and no training on outputs from providers whose terms forbid it.

## Open questions

| ID | Question | Affects |
|---|---|---|
| OQ-1 | Should INU understand and reply in Hinglish, or English only? | STT/TTS model choice (Phase 6), STT finetune (Phase 39) |
| OQ-2 | Public or private GitHub repository? | CI minutes, license, portfolio visibility |

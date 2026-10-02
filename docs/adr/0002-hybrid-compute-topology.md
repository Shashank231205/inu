# 0002. Hybrid compute topology

- **Status:** accepted
- **Date:** 2026-10-02

## Context

The target is movie-level voice latency (NFR-1) at zero cost (NFR-5). The laptop GPU has 4 GB of VRAM, which fits roughly one 3–4B model at Q4. Free cloud GPUs exist, but each is limited:

- Kaggle and Lightning give a fixed number of hours.
- Colab's free tier forbids running web services.
- HF ZeroGPU gives minutes per day.
- Oracle's free VM has no GPU.

A cloud round trip from India also adds 200–400 ms.

## Decision

Split the work by its latency needs:

| Tier | Where | Responsibility |
|---|---|---|
| Reflex | Laptop | Wake word, VAD, speaker ID, STT, TTS, fast local model through Ollama. Works offline. |
| Big brain | Free inference APIs (Groq, Gemini, OpenRouter, Cerebras) behind one provider interface | Hard reasoning, long answers, vision. Optional, and turned off in private mode. |
| Spine | Oracle Always Free ARM VM | Postgres + pgvector, API, scheduler, nightly jobs, model registry, observability |
| Gym | Kaggle, Modal, Lightning | Finetuning, evals, heavy simulations. Batch jobs only. |
| Network | Tailscale | Private mesh between devices. No public endpoints. |

## Alternatives considered

| Option | Why not |
|---|---|
| Everything on the laptop | Only small models fit, so hard reasoning suffers; nothing runs while the laptop is off |
| Main model on a free cloud GPU | No free tier allows 24/7 serving; the round trip breaks the latency budget |
| Paid GPU hosting | Breaks NFR-5 |

## Consequences

- Free-tier limits change. Every provider is an adapter, and its limits live in config.
- Two deployment targets (Windows x86 laptop, Linux ARM VM), so CI must cover both.
- Private mode must be enforced in the router, not left to convention.

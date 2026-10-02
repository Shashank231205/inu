# 0006. Audio I/O: PortAudio over WASAPI, lock-free rings, LQ resampling, 1 ms GIL switching

- **Status:** accepted
- **Date:** 2026-10-02

## Context

The voice loop must capture and play audio continuously, with no dropouts, while the same laptop runs speech recognition, a language model and speech synthesis (NFR-1, NFR-3).

The audio callback runs on a real-time thread, but in Python it still needs the GIL. Every millisecond added between the microphone and the speech recognizer, or between speech synthesis and the speaker, comes out of the 900 ms budget.

All measurements below were taken on the target laptop: i7-11800H, Intel SST microphone array, Realtek speakers, Windows 11.

## Decision

1. **PortAudio through `sounddevice`, on WASAPI shared mode.**
   - PortAudio's Windows default is MME, which runs with tens of milliseconds of buffering. WASAPI reports 2–3 ms device latency here.
   - Shared mode, not exclusive: exclusive mode would lock other apps out of the speakers and mic.
   - The host API is a config value, so other machines can choose their own.
2. **A single-producer/single-consumer ring buffer with no locks** between the audio thread and asyncio. The audio thread only copies samples and signals. Resampling and framing happen on the consumer side. Barge-in discards audio by sending the consumer a *request*, so each index keeps exactly one writer.
3. **soxr streaming resampling at quality `LQ` by default.** Measured delay added by the streaming resampler, in 10 ms chunks:

   | Quality | 48 → 16 kHz (mic → STT) | 24 → 48 kHz (TTS → speaker) | CPU per 10 ms chunk |
   |---|---|---|---|
   | VHQ | 30 ms | 20 ms | ~5 µs |
   | HQ (soxr default) | 20 ms | 30 ms | ~4 µs |
   | MQ | 30 ms | 30 ms | ~4 µs |
   | **LQ** | **≤10 ms** | **≤10 ms** | ~4 µs |

   Speech recognition and speech synthesis gain nothing audible from higher quality, while LQ saves 10–20 ms on each side of the critical path.

4. **Shorten CPython's GIL switch interval to 1 ms while the audio engine runs.** 30 s benchmark with 13 of 16 cores busy and one pure-Python thread competing for the GIL:

   | Switch interval | Audio delivered | Capture lag p50 / p99 | Result |
   |---|---|---|---|
   | 5 ms (CPython default) | 69% in, 71% out | 30.2 / 82.5 ms | FAIL |
   | **1 ms** | **100% in, 100% out** | **21.4 / 33.6 ms** | **PASS** |

   At 5 ms, WASAPI **dropped 31% of the audio without setting any overflow flag**.

5. **Delivered audio is checked against wall-clock time.** Because of finding 4, xrun counters alone can't prove there are no dropouts. Each direction counts the samples it delivered. The benchmark fails below 99% coverage.

6. **Supervision:** a stream counts as lost when it stops *or* stalls (no callbacks for `stall_timeout_ms`). The engine then rescans and reopens, falling back to the default device if the configured one is gone. On first start, a missing device is an error, so config typos fail loudly.

7. **Packaging:** audio lives in the separate `inu-voice` package. The VM never installs PortAudio, numpy or soxr.

## Results (Phase 5 done-when: no dropouts at 80% CPU load)

`inu audio bench --seconds 30 --cpu-load 0.8`, laptop profile:

| Load | Audio delivered | Overruns / underruns / driver xruns | Capture → consumer p50 / p99 / max |
|---|---|---|---|
| 13 busy processes | 100.0% / 100.0% | 0 / 0 / 0 | 20.2 / 20.6 / 29.1 ms |
| 13 busy processes + GIL-bound thread | 100.0% / 100.0% | 0 / 0 / 0 | 21.4 / 33.6 / 37.8 ms |

The ~20 ms floor is the 10 ms callback block plus the LQ resampler.

## Alternatives considered

| Option | Why not |
|---|---|
| PyAudio | Less maintained; its callback API exposes raw bytes instead of numpy arrays |
| WASAPI exclusive mode | Lower latency, but takes the devices away from every other app on the laptop |
| A separate audio process with a shared-memory ring | Immune to the GIL, but adds IPC and lifecycle complexity. Not needed at the measured numbers; revisit if Phase 11 profiling says otherwise. |
| Polling the ring from asyncio instead of signalling | Removes the `call_soon_threadsafe` in the callback, but adds up to one poll interval of latency. Revisit in Phase 11. |
| scipy / numpy resampling | Not streaming: chunk boundaries cause clicks, or whole buffers are needed |

## Consequences

- The GIL setting is process-wide: CPU-bound Python threads in the voice process switch more often, at a small throughput cost. It's restored when the engine closes.
- Stream start shows a one-off burst of about 200 ms lag at t ≈ 0.2 s (WASAPI pre-buffering). The benchmark excludes the first 0.5 s from lag statistics and says so in its output.
- PortAudio doesn't follow changes of the Windows default device on its own. INU picks up a new default only after the current stream is lost.

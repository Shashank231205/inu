# Audio I/O

The `inu-voice` package captures the microphone and plays to the speakers. The design and the measurements behind it are in [ADR 0006](adr/0006-audio-io.md).

## Pieces

| Component | Job |
|---|---|
| `AudioEngine` | Opens both streams from config, supervises them, reconnects, and sets the GIL switch interval |
| `Microphone` | Device audio → 16 kHz mono `AudioFrame`s of `frame_ms`, each stamped with when its last sample was captured |
| `Speaker` | `play()` with backpressure and resampling, `clear()` for barge-in (silent within one block), `drain()` |
| `RingBuffer` | Lock-free single-producer/single-consumer sample buffer between the audio thread and asyncio |
| `AudioBackend` | Hardware interface. `SoundDeviceBackend` is the real one; tests use a fake. |

```python
async with AudioEngine(settings.audio, SoundDeviceBackend()) as engine:
    async for frame in engine.microphone.frames():  # one consumer at a time
        ...
    await engine.speaker.play(pcm, 24_000, final=False)  # stream TTS chunks
    engine.speaker.clear()  # barge-in
```

## Configuration

```yaml
audio:
  host_api: Windows WASAPI      # laptop profile; null = PortAudio default (MME, slow)
  pipeline_sample_rate: 16000
  frame_ms: 20
  resample_quality: LQ          # QQ | LQ | MQ | HQ | VHQ
  reconnect_interval_ms: 1000
  stall_timeout_ms: 1000
  gil_switch_interval_ms: 1
  input:  {device: null, sample_rate: null, block_ms: 10, buffer_ms: 2000}
  output: {device: null, sample_rate: null, block_ms: 10, buffer_ms: 10000}
```

`device` is a case-insensitive part of the device name, for example `device: headset`.

## Commands

```sh
uv run inu --profile laptop audio devices
uv run inu --profile laptop audio bench --seconds 30 --cpu-load 0.8 [--gil-load]
```

- **`devices`** lists every device and marks the ones the profile selects.
- **`bench`** captures and plays at the same time while other processes keep the CPU busy.
  - **It fails if:** any overrun, underrun, driver xrun or reconnect happens, or less than 99% of wall time is delivered as audio.
  - **It also reports:** capture → consumer lag.

## Metrics

| Metric | Type | Attributes |
|---|---|---|
| `inu.audio.xruns` | observable counter | `direction` (input, output), `source` (buffer, device) |
| `inu.audio.reconnects` | counter | |

## Tests

- Unit tests use the fake backend and need no hardware.
- `test_hardware.py` opens the real devices. It runs only when you opt in: `INU_TEST_HARDWARE=1 uv run pytest packages/voice/tests/test_hardware.py`.

import asyncio

import numpy as np

from inu_voice.audio import AudioFrame, Microphone
from voice_fakes import FakeClock, audio_settings

PIPELINE_RATE = 16_000
FRAME = 320  # 20 ms at 16 kHz


def tone(freq_hz: float, rate: int, samples: int, start: int = 0) -> np.ndarray:
    t = np.arange(start, start + samples) / rate
    return (0.5 * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)


async def collect(mic: Microphone, count: int) -> list[AudioFrame]:
    frames: list[AudioFrame] = []

    async def take() -> None:
        async for frame in mic.frames():
            frames.append(frame)
            if len(frames) == count:
                return

    await asyncio.wait_for(take(), timeout=2)
    return frames


async def test_resamples_device_audio_into_fixed_pipeline_frames() -> None:
    mic = Microphone(audio_settings(), FakeClock())
    callback = mic.attach(48_000, asyncio.get_running_loop())
    for block in range(30):  # 300 ms of a 1 kHz tone in 10 ms blocks
        callback(tone(1_000, 48_000, 480, start=block * 480), False)

    frames = await collect(mic, 10)

    assert all(f.sample_rate == PIPELINE_RATE and len(f.samples) == FRAME for f in frames)
    signal = np.concatenate([f.samples for f in frames[2:]])  # skip resampler warm-up
    spectrum = np.abs(np.fft.rfft(signal))
    peak_hz = np.argmax(spectrum) * PIPELINE_RATE / len(signal)
    assert abs(peak_hz - 1_000) < 30


async def test_passes_audio_through_untouched_at_the_pipeline_rate() -> None:
    mic = Microphone(audio_settings(), FakeClock())
    callback = mic.attach(PIPELINE_RATE, asyncio.get_running_loop())
    ramp = np.arange(4 * FRAME, dtype=np.float32)
    for start in range(0, len(ramp), 160):
        callback(ramp[start : start + 160], False)

    frames = await collect(mic, 4)

    np.testing.assert_array_equal(np.concatenate([f.samples for f in frames]), ramp)


async def test_timestamps_mark_when_each_frame_finished_capturing() -> None:
    clock = FakeClock(start_ns=0)
    mic = Microphone(audio_settings(), clock)
    callback = mic.attach(PIPELINE_RATE, asyncio.get_running_loop())
    for _ in range(3):  # three 10 ms blocks, arriving 10 ms apart
        clock.advance_ms(10)
        callback(np.zeros(160, dtype=np.float32), False)

    (frame,) = await collect(mic, 1)

    # The frame's last sample was the end of block 2, captured at t = 20 ms.
    assert frame.captured_at_ns == 20_000_000


async def test_full_ring_counts_an_overrun_instead_of_blocking() -> None:
    mic = Microphone(audio_settings(input={"buffer_ms": 40}), FakeClock())
    callback = mic.attach(PIPELINE_RATE, asyncio.get_running_loop())
    for _ in range(10):  # 100 ms into a 40 ms ring, with nobody reading
        callback(np.zeros(160, dtype=np.float32), False)

    assert mic.stats.xruns == 6
    assert mic.stats.callbacks == 10


async def test_driver_reported_overflow_is_counted_separately() -> None:
    mic = Microphone(audio_settings(), FakeClock())
    callback = mic.attach(PIPELINE_RATE, asyncio.get_running_loop())
    callback(np.zeros(160, dtype=np.float32), True)
    assert (mic.stats.device_xruns, mic.stats.xruns) == (1, 0)


async def test_reattach_starts_a_fresh_session() -> None:
    mic = Microphone(audio_settings(), FakeClock())
    loop = asyncio.get_running_loop()
    old = mic.attach(PIPELINE_RATE, loop)
    old(np.ones(100, dtype=np.float32), False)  # partial frame, then the device drops
    new = mic.attach(PIPELINE_RATE, loop)
    new(np.zeros(FRAME, dtype=np.float32), False)

    (frame,) = await collect(mic, 1)

    assert not frame.samples.any()  # no leftovers from the old stream

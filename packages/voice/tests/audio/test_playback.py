import asyncio

import numpy as np
import pytest

from inu_voice.audio import AudioDeviceError, Speaker
from inu_voice.audio.types import OutputCallback
from voice_fakes import FakeClock, audio_settings

RATE = 48_000
BLOCK = 480


def pull(callback: OutputCallback, samples: int = BLOCK, underflow: bool = False) -> np.ndarray:
    out = np.full(samples, np.nan, dtype=np.float32)
    callback(out, underflow)
    return out


async def settle() -> None:
    for _ in range(3):
        await asyncio.sleep(0)


async def test_plays_queued_audio_then_silence() -> None:
    speaker = Speaker(audio_settings(), FakeClock())
    callback = speaker.attach(RATE, asyncio.get_running_loop())
    assert await speaker.play(np.full(300, 0.25, dtype=np.float32), RATE)

    out = pull(callback)

    assert (out[:300] == 0.25).all()
    assert (out[300:] == 0.0).all()


async def test_resamples_to_the_device_rate() -> None:
    speaker = Speaker(audio_settings(), FakeClock())
    speaker.attach(RATE, asyncio.get_running_loop())
    await speaker.play(np.zeros(2_400, dtype=np.float32), 24_000)  # 100 ms at 24 kHz
    assert speaker.buffered_ms == pytest.approx(100, abs=1)


async def test_streamed_chunks_share_one_resampler() -> None:
    speaker = Speaker(audio_settings(), FakeClock())
    speaker.attach(RATE, asyncio.get_running_loop())
    for _ in range(4):
        await speaker.play(np.zeros(600, dtype=np.float32), 24_000, final=False)
    await speaker.play(np.zeros(600, dtype=np.float32), 24_000, final=True)
    assert speaker.buffered_ms == pytest.approx(125, abs=1)  # 5 x 25 ms, nothing lost


async def test_full_buffer_applies_backpressure() -> None:
    speaker = Speaker(audio_settings(output={"buffer_ms": 40}), FakeClock())
    callback = speaker.attach(RATE, asyncio.get_running_loop())
    playing = asyncio.create_task(speaker.play(np.zeros(4_800, dtype=np.float32), RATE))
    await settle()
    assert not playing.done()  # 100 ms does not fit in a 40 ms ring

    while not playing.done():
        pull(callback)
        await settle()

    assert playing.result() is True


async def test_clear_silences_within_one_block_and_cancels_writers() -> None:
    speaker = Speaker(audio_settings(output={"buffer_ms": 40}), FakeClock())
    callback = speaker.attach(RATE, asyncio.get_running_loop())
    playing = asyncio.create_task(speaker.play(np.ones(9_600, dtype=np.float32), RATE))
    await settle()

    speaker.clear()
    await settle()

    assert playing.result() is False
    assert (pull(callback) == 0.0).all()


async def test_underrun_counts_only_inside_an_open_utterance() -> None:
    speaker = Speaker(audio_settings(), FakeClock())
    callback = speaker.attach(RATE, asyncio.get_running_loop())

    pull(callback)  # idle: silence is expected, not a dropout
    assert speaker.stats.xruns == 0

    await speaker.play(np.zeros(100, dtype=np.float32), RATE, final=False)
    pull(callback)  # mid-utterance and the producer fell behind
    assert speaker.stats.xruns == 1

    await speaker.play(np.zeros(100, dtype=np.float32), RATE, final=True)
    pull(callback)
    pull(callback)  # tail played out; the utterance is over
    assert speaker.stats.xruns == 1


async def test_drain_waits_until_everything_is_played() -> None:
    speaker = Speaker(audio_settings(), FakeClock())
    callback = speaker.attach(RATE, asyncio.get_running_loop())
    await speaker.play(np.zeros(2 * BLOCK, dtype=np.float32), RATE)
    draining = asyncio.create_task(speaker.drain())

    pull(callback)
    await settle()
    assert not draining.done()
    pull(callback)
    await settle()
    assert draining.done()


async def test_drain_completes_after_clear() -> None:
    speaker = Speaker(audio_settings(), FakeClock())
    callback = speaker.attach(RATE, asyncio.get_running_loop())
    await speaker.play(np.zeros(10 * BLOCK, dtype=np.float32), RATE)
    speaker.clear()
    pull(callback)
    await asyncio.wait_for(speaker.drain(), timeout=1)


async def test_driver_reported_underflow_is_counted() -> None:
    speaker = Speaker(audio_settings(), FakeClock())
    callback = speaker.attach(RATE, asyncio.get_running_loop())
    pull(callback, underflow=True)
    assert speaker.stats.device_xruns == 1


async def test_playing_before_any_stream_is_an_error() -> None:
    speaker = Speaker(audio_settings(), FakeClock())
    with pytest.raises(AudioDeviceError, match="not attached"):
        await speaker.play(np.zeros(10, dtype=np.float32), RATE)


async def test_callbacks_from_a_replaced_stream_are_ignored() -> None:
    speaker = Speaker(audio_settings(), FakeClock())
    loop = asyncio.get_running_loop()
    old = speaker.attach(RATE, loop)
    speaker.attach(RATE, loop)
    await speaker.play(np.zeros(BLOCK, dtype=np.float32), RATE)

    pull(old)
    await settle()

    assert speaker.buffered_ms == pytest.approx(10)  # the new ring is untouched

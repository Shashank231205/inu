import asyncio
import contextlib

import numpy as np

from inu_voice.audio import AudioEngine
from inu_voice.audio.bench import run_bench
from voice_fakes import FakeBackend, audio_settings


async def pump(backend: FakeBackend) -> None:
    """Drive the fake streams in real time, the way PortAudio would."""
    while True:
        await asyncio.sleep(0.01)
        mic, speaker = backend.inputs[-1], backend.outputs[-1]
        mic.callback(np.zeros(mic.block, dtype=np.float32), False)
        speaker.callback(np.zeros(speaker.block, dtype=np.float32), False)


async def test_bench_reports_a_clean_run() -> None:
    backend = FakeBackend()
    async with AudioEngine(audio_settings(), backend) as engine:
        driver = asyncio.create_task(pump(backend))
        try:
            # Long enough to measure past the warm-up window.
            report = await run_bench(engine, seconds=1.2, cpu_burners=1, gil_load=True)
        finally:
            driver.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await driver

    assert report.frames > 0
    assert report.input_callbacks > 0
    assert report.output_callbacks > 0
    assert report.capture_overruns == report.device_xruns == report.reconnects == 0
    assert report.lag_p50_ms >= 0
    assert "Microphone Array" in report.render()


async def test_bench_fails_when_no_audio_arrives() -> None:
    backend = FakeBackend()
    async with AudioEngine(audio_settings(), backend) as engine:
        report = await run_bench(engine, seconds=0.05, cpu_burners=0, gil_load=False)
    assert not report.passed
    assert "FAIL" in report.render()

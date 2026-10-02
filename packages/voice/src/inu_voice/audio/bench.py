"""Dropout benchmark: run capture and playback together under load.

Load comes from two places:
* `cpu_burners` other processes spinning, which competes with the audio thread
  for cores the way inference does.
* An optional pure-Python thread in this process, which competes for the GIL that
  the audio callbacks need.

Playback is fed silence the way streaming TTS would feed speech: small chunks kept
about `target_buffer_ms` ahead, so a starved event loop shows up as an underrun.
"""

import asyncio
import contextlib
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from inu_voice.audio.engine import AudioEngine
from inu_voice.audio.types import DeviceKind

NS_PER_MS = 1_000_000
FEED_CHUNK_MS = 20
FEED_RATE = 24_000  # Kokoro TTS output rate, so playback also exercises resampling
# Drivers can drop audio without flagging it (WASAPI does when callbacks run late),
# so delivered audio is checked against wall time as well as the xrun counters.
MIN_COVERAGE = 0.99
# WASAPI delivers a burst of pre-buffered audio when a stream starts (~200 ms lag at
# t = 0.2 s in every run). That's a one-off, not steady-state latency, so lag stats skip it.
WARMUP_S = 0.5


@dataclass(frozen=True)
class BenchReport:
    seconds: float
    cpu_burners: int
    gil_load: bool
    input_device: str
    output_device: str
    input_callbacks: int
    output_callbacks: int
    input_coverage: float  # audio delivered / wall time
    output_coverage: float
    capture_overruns: int
    playback_underruns: int
    device_xruns: int
    reconnects: int
    frames: int
    lag_p50_ms: float
    lag_p99_ms: float
    lag_max_ms: float
    lag_max_at_s: float  # when in the run the worst lag happened

    @property
    def passed(self) -> bool:
        return (
            self.frames > 0
            and self.input_coverage >= MIN_COVERAGE
            and self.output_coverage >= MIN_COVERAGE
            and self.capture_overruns == 0
            and self.playback_underruns == 0
            and self.device_xruns == 0
            and self.reconnects == 0
        )

    def render(self) -> str:
        return "\n".join(
            [
                f"duration            {self.seconds:.1f} s",
                f"load                {self.cpu_burners} busy processes"
                + (" + GIL-bound thread" if self.gil_load else ""),
                f"input               {self.input_device}",
                f"output              {self.output_device}",
                f"callbacks in/out    {self.input_callbacks} / {self.output_callbacks}",
                f"audio delivered     in {self.input_coverage:.1%}, out {self.output_coverage:.1%}"
                f" of wall time (need {MIN_COVERAGE:.0%})",
                f"capture overruns    {self.capture_overruns}",
                f"playback underruns  {self.playback_underruns}",
                f"device xruns        {self.device_xruns}",
                f"reconnects          {self.reconnects}",
                f"frames received     {self.frames}",
                f"capture->consumer   p50 {self.lag_p50_ms:.1f} ms, p99 {self.lag_p99_ms:.1f} ms,"
                f" max {self.lag_max_ms:.1f} ms at {self.lag_max_at_s:.2f} s"
                f" (after {WARMUP_S} s warm-up)",
                f"result              {'PASS' if self.passed else 'FAIL'}",
            ]
        )


async def run_bench(
    engine: AudioEngine,
    *,
    seconds: float,
    cpu_burners: int,
    gil_load: bool,
    target_buffer_ms: float = 100.0,
) -> BenchReport:
    """Run against a started engine. Stats are deltas over the run."""
    mic, speaker = engine.microphone, engine.speaker
    before = (
        mic.stats.callbacks,
        speaker.stats.callbacks,
        mic.stats.xruns,
        speaker.stats.xruns,
        mic.stats.device_xruns + speaker.stats.device_xruns,
        engine.reconnects,
        mic.stats.samples,
        speaker.stats.samples,
    )
    lags_ms: list[float] = []
    lag_times_s: list[float] = []
    started_ns = time.perf_counter_ns()

    async def consume() -> None:
        # The stream never ends and this task is cancelled, so record as frames arrive:
        # a comprehension would lose everything on cancellation.
        async for frame in mic.frames():
            now = time.perf_counter_ns()
            at_s = (now - started_ns) / 1e9
            if at_s >= WARMUP_S:
                lags_ms.append((now - frame.captured_at_ns) / NS_PER_MS)
                lag_times_s.append(at_s)

    async def feed() -> None:
        chunk = np.zeros(FEED_RATE * FEED_CHUNK_MS // 1000, dtype=np.float32)
        while True:
            if speaker.buffered_ms < target_buffer_ms:
                await speaker.play(chunk, FEED_RATE, final=False)
            else:
                await asyncio.sleep(0.005)

    with _cpu_load(cpu_burners), _gil_load(gil_load):
        tasks = [asyncio.create_task(consume()), asyncio.create_task(feed())]
        await asyncio.sleep(seconds)
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
    elapsed_s = (time.perf_counter_ns() - started_ns) / 1e9
    speaker.clear()

    def coverage(kind: DeviceKind, samples: int) -> float:
        return samples / engine.devices[kind][1] / elapsed_s

    lags = np.array(lags_ms) if lags_ms else np.zeros(1)
    worst = int(np.argmax(lags))
    return BenchReport(
        seconds=seconds,
        cpu_burners=cpu_burners,
        gil_load=gil_load,
        input_device=engine.devices[DeviceKind.INPUT][0].describe(),
        output_device=engine.devices[DeviceKind.OUTPUT][0].describe(),
        input_callbacks=mic.stats.callbacks - before[0],
        output_callbacks=speaker.stats.callbacks - before[1],
        input_coverage=coverage(DeviceKind.INPUT, mic.stats.samples - before[6]),
        output_coverage=coverage(DeviceKind.OUTPUT, speaker.stats.samples - before[7]),
        capture_overruns=mic.stats.xruns - before[2],
        playback_underruns=speaker.stats.xruns - before[3],
        device_xruns=mic.stats.device_xruns + speaker.stats.device_xruns - before[4],
        reconnects=engine.reconnects - before[5],
        frames=len(lags_ms),
        lag_p50_ms=float(np.percentile(lags, 50)),
        lag_p99_ms=float(np.percentile(lags, 99)),
        lag_max_ms=float(lags[worst]),
        lag_max_at_s=lag_times_s[worst] if lag_times_s else 0.0,
    )


@contextlib.contextmanager
def _cpu_load(processes: int) -> Iterator[None]:
    burners = [
        subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(processes)
    ]
    try:
        yield
    finally:
        for burner in burners:
            burner.kill()
        for burner in burners:
            burner.wait()


@contextlib.contextmanager
def _gil_load(enabled: bool) -> Iterator[None]:
    stop = threading.Event()

    def spin() -> None:
        while not stop.is_set():
            _ = sum(range(10_000))  # pure-Python work that holds the GIL

    thread = threading.Thread(target=spin, daemon=True)
    if enabled:
        thread.start()
    try:
        yield
    finally:
        stop.set()
        if enabled:
            thread.join()

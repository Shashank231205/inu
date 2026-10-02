"""Microphone capture.

The audio thread only copies each block into a ring buffer and signals the event
loop. Resampling to the pipeline rate and cutting fixed-length frames happen on the
consumer side, where taking time cannot cause a dropout.
"""

import asyncio
from collections.abc import AsyncIterator, Callable

import numpy as np
import soxr

from inu.config import AudioSettings
from inu_voice.audio.ring import RingBuffer
from inu_voice.audio.stats import AudioStats
from inu_voice.audio.types import AudioFrame, InputCallback, Samples

NS_PER_S = 1_000_000_000


class Microphone:
    """Turns device audio into `AudioFrame`s. One consumer at a time."""

    def __init__(self, settings: AudioSettings, clock: Callable[[], int]) -> None:
        self._pipeline_rate = settings.pipeline_sample_rate
        self._frame_samples = settings.pipeline_sample_rate * settings.frame_ms // 1000
        self._buffer_ms = settings.input.buffer_ms
        self._quality = settings.resample_quality.value
        self._clock = clock
        self._ready = asyncio.Event()
        self._session: _CaptureSession | None = None
        self.stats = AudioStats()

    @property
    def frame_samples(self) -> int:
        return self._frame_samples

    def attach(self, device_rate: int, loop: asyncio.AbstractEventLoop) -> InputCallback:
        """Start a new capture session for a freshly opened stream."""
        session = _CaptureSession(
            device_rate=device_rate,
            pipeline_rate=self._pipeline_rate,
            frame_samples=self._frame_samples,
            ring=RingBuffer(device_rate * self._buffer_ms // 1000),
            quality=self._quality,
            now_ns=self._clock(),
        )
        self._session = session
        self.stats.last_callback_ns = self._clock()
        stats, clock, ready = self.stats, self._clock, self._ready

        def on_audio(block: Samples, device_overflow: bool) -> None:
            if session.ring.write(block) < len(block):
                stats.xruns += 1
            if device_overflow:
                stats.device_xruns += 1
            now = clock()
            session.stamp = (session.ring.written, now)
            stats.callbacks += 1
            stats.samples += len(block)
            stats.last_callback_ns = now
            loop.call_soon_threadsafe(ready.set)

        return on_audio

    async def frames(self) -> AsyncIterator[AudioFrame]:
        """Yield frames as audio arrives, across stream reconnects."""
        while True:
            await self._ready.wait()
            self._ready.clear()
            if self._session is not None:
                for frame in self._session.drain():
                    yield frame


class _CaptureSession:
    """State tied to one open input stream."""

    def __init__(
        self,
        *,
        device_rate: int,
        pipeline_rate: int,
        frame_samples: int,
        ring: RingBuffer,
        quality: str,
        now_ns: int,
    ) -> None:
        self.device_rate = device_rate
        self.pipeline_rate = pipeline_rate
        self.frame_samples = frame_samples
        self.ring = ring
        self.resampler = (
            None
            if device_rate == pipeline_rate
            else soxr.ResampleStream(
                device_rate, pipeline_rate, 1, dtype="float32", quality=quality
            )
        )
        self.pending: Samples = np.empty(0, dtype=np.float32)
        self.emitted = 0  # pipeline-rate samples handed out as frames
        # (device samples written, clock) at the latest callback; one tuple so the
        # audio thread replaces both values in a single atomic rebind.
        self.stamp: tuple[int, int] = (0, now_ns)

    def drain(self) -> list[AudioFrame]:
        raw = self.ring.read()
        if not len(raw):
            return []
        converted = self.resampler.resample_chunk(raw) if self.resampler else raw
        self.pending = np.concatenate((self.pending, converted))

        written, stamp_ns = self.stamp
        count = len(self.pending) // self.frame_samples
        frames = []
        for index in range(count):
            start = index * self.frame_samples
            self.emitted += self.frame_samples
            # soxr keeps output time-aligned with input, so a pipeline sample maps
            # straight back to the device sample it came from.
            end_on_device = self.emitted * self.device_rate / self.pipeline_rate
            age_ns = int((written - end_on_device) * NS_PER_S / self.device_rate)
            frames.append(
                AudioFrame(
                    samples=self.pending[start : start + self.frame_samples].copy(),
                    sample_rate=self.pipeline_rate,
                    captured_at_ns=stamp_ns - age_ns,
                )
            )
        self.pending = self.pending[count * self.frame_samples :]
        return frames

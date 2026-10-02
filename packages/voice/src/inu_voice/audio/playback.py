"""Speaker playback.

`play()` resamples to the device rate and writes into a ring buffer, waiting when it
is full (backpressure). The audio thread drains the ring and plays silence when it
is empty. `clear()` stops sound within one audio block, which is how barge-in will
cut INU off mid-sentence.
"""

import asyncio
from collections.abc import Callable

import numpy as np
import soxr

from inu.config import AudioSettings
from inu_voice.audio.ring import RingBuffer
from inu_voice.audio.stats import AudioStats
from inu_voice.audio.types import AudioDeviceError, OutputCallback, Samples


class Speaker:
    def __init__(self, settings: AudioSettings, clock: Callable[[], int]) -> None:
        self._buffer_ms = settings.output.buffer_ms
        self._quality = settings.resample_quality.value
        self._clock = clock
        self._ring: RingBuffer | None = None
        self._device_rate = 0
        self._resamplers: dict[int, soxr.ResampleStream] = {}
        self._generation = 0  # bumped by clear() and reconnects; stale writers stop
        self._utterance_open = False  # between the first and final chunk of an utterance
        self._space = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._signal_idle = False
        self.stats = AudioStats()

    @property
    def buffered_ms(self) -> float:
        if self._ring is None:
            return 0.0
        return self._ring.available() * 1000 / self._device_rate

    def attach(self, device_rate: int, loop: asyncio.AbstractEventLoop) -> OutputCallback:
        """Start a new playback session. Audio still queued for the old stream is dropped."""
        ring = RingBuffer(device_rate * self._buffer_ms // 1000)
        self._ring, self._device_rate = ring, device_rate
        self._resamplers.clear()
        self._generation += 1
        self._utterance_open = False
        self._space.set()
        self._idle.set()
        self.stats.last_callback_ns = self._clock()
        stats, clock = self.stats, self._clock

        def on_request(out: Samples, device_underflow: bool) -> None:
            got = ring.read_into(out)
            if got < len(out):
                out[got:] = 0.0
                if self._utterance_open:
                    stats.xruns += 1
            if device_underflow:
                stats.device_xruns += 1
            stats.callbacks += 1
            stats.samples += len(out)
            stats.last_callback_ns = clock()
            if got or self._signal_idle:
                loop.call_soon_threadsafe(self._on_consumed, ring)

        return on_request

    async def play(self, samples: Samples, sample_rate: int, *, final: bool = True) -> bool:
        """Queue audio. Stream an utterance as several calls with `final=False` on all
        but the last. Returns False if clear() or a reconnect cut it short."""
        ring = self._ring
        if ring is None:
            raise AudioDeviceError("Speaker is not attached to an output stream")
        generation = self._generation
        self._utterance_open = not final
        data = self._resample(samples, sample_rate, final=final)

        offset = 0
        while offset < len(data):
            if generation != self._generation:
                return False
            offset += ring.write(data[offset:])
            self._idle.clear()
            self._signal_idle = True
            if offset < len(data):
                self._space.clear()
                if ring.free() == 0:  # re-check after clear(): no lost wake-up
                    await self._space.wait()
        return generation == self._generation

    def clear(self) -> None:
        """Stop playback now and abandon anything queued or being queued."""
        if self._ring is not None:
            self._ring.request_discard()
        self._generation += 1
        self._resamplers.clear()
        self._utterance_open = False
        self._signal_idle = True
        self._space.set()

    async def drain(self) -> None:
        """Wait until everything queued has been played."""
        await self._idle.wait()

    def _resample(self, samples: Samples, sample_rate: int, *, final: bool) -> Samples:
        samples = np.asarray(samples, dtype=np.float32)
        if sample_rate == self._device_rate:
            return samples
        stream = self._resamplers.get(sample_rate)
        if stream is None:
            stream = soxr.ResampleStream(
                sample_rate, self._device_rate, 1, dtype="float32", quality=self._quality
            )
            self._resamplers[sample_rate] = stream
        converted: Samples = stream.resample_chunk(samples, last=final)
        if final:
            del self._resamplers[sample_rate]
        return converted

    def _on_consumed(self, ring: RingBuffer) -> None:
        if ring is not self._ring:
            return  # a late callback from a stream that has since been replaced
        self._space.set()
        if ring.available() == 0:
            self._signal_idle = False
            self._idle.set()

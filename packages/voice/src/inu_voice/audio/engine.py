"""Audio engine: opens the streams, then keeps them alive.

A supervisor task checks the streams every `reconnect_interval_ms`. A stream counts as
lost when the backend says it stopped, or when no callback has arrived for
`stall_timeout_ms`. That second check matters on Windows, where a stream on an
unplugged device can stay "active" but silent. Recovery closes both streams, rescans
devices and reopens. If the configured device is gone, it falls back to the host API's
default. On first start, a missing configured device is an error instead, so a typo in
config fails loudly.

While running, the engine shortens CPython's GIL switch interval. Audio callbacks need
the GIL, and at the 5 ms default a busy Python thread made Windows drop 31% of the
audio without reporting it (ADR 0006). The previous value is restored on close.
"""

import asyncio
import contextlib
import sys
import time
import weakref
from collections.abc import Callable, Iterable
from types import TracebackType
from typing import Self

import structlog
from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Observation

from inu.config import AudioDirectionSettings, AudioSettings
from inu_voice.audio.capture import Microphone
from inu_voice.audio.devices import select_device
from inu_voice.audio.playback import Speaker
from inu_voice.audio.types import (
    AudioBackend,
    AudioDevice,
    AudioDeviceError,
    DeviceKind,
    StreamHandle,
)

NS_PER_MS = 1_000_000

log = structlog.get_logger(__name__)

_live_engines: "weakref.WeakSet[AudioEngine]" = weakref.WeakSet()


def _observe_xruns(_: CallbackOptions) -> Iterable[Observation]:
    for engine in list(_live_engines):
        for direction, stats in (
            ("input", engine.microphone.stats),
            ("output", engine.speaker.stats),
        ):
            yield Observation(stats.xruns, {"direction": direction, "source": "buffer"})
            yield Observation(stats.device_xruns, {"direction": direction, "source": "device"})


_meter = metrics.get_meter("inu.audio")
_meter.create_observable_counter(
    "inu.audio.xruns",
    callbacks=[_observe_xruns],
    description="Audio dropouts: capture overruns and playback underruns",
)
_reconnects = _meter.create_counter("inu.audio.reconnects", description="Audio stream recoveries")


class AudioEngine:
    def __init__(
        self,
        settings: AudioSettings,
        backend: AudioBackend,
        *,
        clock: Callable[[], int] = time.perf_counter_ns,
    ) -> None:
        self._settings = settings
        self._backend = backend
        self._clock = clock
        self._streams: list[StreamHandle] = []
        self._supervisor: asyncio.Task[None] | None = None
        self._previous_switch_interval = sys.getswitchinterval()
        self.microphone = Microphone(settings, clock)
        self.speaker = Speaker(settings, clock)
        self.devices: dict[DeviceKind, tuple[AudioDevice, int]] = {}  # device, sample rate
        self.reconnects = 0
        _live_engines.add(self)

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._previous_switch_interval = sys.getswitchinterval()
        sys.setswitchinterval(self._settings.gil_switch_interval_ms / 1000)
        try:
            self._open(loop, strict=True)
        except BaseException:
            sys.setswitchinterval(self._previous_switch_interval)
            raise
        self._supervisor = asyncio.create_task(self._supervise(loop), name="audio-supervisor")

    async def close(self) -> None:
        if self._supervisor is not None:
            self._supervisor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._supervisor
            self._supervisor = None
            sys.setswitchinterval(self._previous_switch_interval)
        self._close_streams()

    def healthy(self) -> bool:
        if not self._streams or not all(stream.active for stream in self._streams):
            return False
        cutoff = self._clock() - self._settings.stall_timeout_ms * NS_PER_MS
        return (
            self.microphone.stats.last_callback_ns > cutoff
            and self.speaker.stats.last_callback_ns > cutoff
        )

    # ------------------------------------------------------------------ internals

    def _open(self, loop: asyncio.AbstractEventLoop, *, strict: bool) -> None:
        settings = self._settings
        input_device = self._select(DeviceKind.INPUT, settings.input, strict=strict)
        output_device = self._select(DeviceKind.OUTPUT, settings.output, strict=strict)
        try:
            for kind, device, direction in (
                (DeviceKind.INPUT, input_device, settings.input),
                (DeviceKind.OUTPUT, output_device, settings.output),
            ):
                rate = direction.sample_rate or device.default_sample_rate
                block = rate * direction.block_ms // 1000
                if kind is DeviceKind.INPUT:
                    callback = self.microphone.attach(rate, loop)
                    stream = self._backend.open_input(device, rate, block, callback)
                else:
                    stream = self._backend.open_output(
                        device, rate, block, self.speaker.attach(rate, loop)
                    )
                self._streams.append(stream)
                self.devices[kind] = (device, rate)
        except BaseException:
            self._close_streams()
            raise
        log.info(
            "audio.opened",
            input=input_device.describe(),
            input_rate=self.devices[DeviceKind.INPUT][1],
            output=output_device.describe(),
            output_rate=self.devices[DeviceKind.OUTPUT][1],
        )

    def _select(
        self, kind: DeviceKind, direction: AudioDirectionSettings, *, strict: bool
    ) -> AudioDevice:
        host_api = self._settings.host_api
        try:
            return select_device(self._backend, kind, host_api, direction.device)
        except AudioDeviceError:
            if strict or direction.device is None:
                raise
            log.warning("audio.device_fallback", kind=kind.value, wanted=direction.device)
            return select_device(self._backend, kind, host_api, None)

    async def _supervise(self, loop: asyncio.AbstractEventLoop) -> None:
        interval = self._settings.reconnect_interval_ms / 1000
        while True:
            await asyncio.sleep(interval)
            if self.healthy():
                continue
            try:
                self._reconnect(loop)
            except Exception:  # keep supervising whatever went wrong
                log.exception("audio.supervisor_error")

    def _reconnect(self, loop: asyncio.AbstractEventLoop) -> None:
        log.warning("audio.stream_lost", streams=len(self._streams))
        self._close_streams()
        try:
            self._backend.rescan()
            self._open(loop, strict=False)
        except AudioDeviceError as exc:
            log.warning("audio.reconnect_failed", reason=exc.message, **exc.attributes())
            return
        self.reconnects += 1
        _reconnects.add(1)
        log.info("audio.reconnected", reconnects=self.reconnects)

    def _close_streams(self) -> None:
        for stream in self._streams:
            stream.close()
        self._streams.clear()

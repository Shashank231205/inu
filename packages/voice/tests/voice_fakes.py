"""Test doubles for audio hardware. Fixtures live in conftest.py."""

import asyncio
import time
from collections.abc import Callable
from typing import Any

from inu.config import AudioSettings
from inu.config.loader import deep_merge
from inu_voice.audio import AudioDevice, AudioDeviceError, DeviceKind
from inu_voice.audio.types import InputCallback, OutputCallback

WASAPI = "Windows WASAPI"
MME = "MME"


def device(
    index: int, name: str, host_api: str, *, inputs: int = 0, outputs: int = 0, rate: int = 48_000
) -> AudioDevice:
    return AudioDevice(index, name, host_api, inputs, outputs, rate)


def laptop_devices() -> list[AudioDevice]:
    return [
        device(0, "Microphone (MME)", MME, inputs=2, rate=44_100),
        device(1, "Speakers (MME)", MME, outputs=2, rate=44_100),
        device(2, "Microphone Array", WASAPI, inputs=2),
        device(3, "Speakers (Realtek)", WASAPI, outputs=2),
        device(4, "USB Headset Mic", WASAPI, inputs=1),
        device(5, "USB Headset", WASAPI, outputs=2),
    ]


LAPTOP_DEFAULTS: dict[tuple[DeviceKind, str | None], int] = {
    (DeviceKind.INPUT, None): 0,
    (DeviceKind.OUTPUT, None): 1,
    (DeviceKind.INPUT, WASAPI): 2,
    (DeviceKind.OUTPUT, WASAPI): 3,
}


class FakeStream:
    def __init__(
        self, device: AudioDevice, rate: int, block: int, callback: Callable[..., None]
    ) -> None:
        self.device, self.rate, self.block, self.callback = device, rate, block, callback
        self.active = True
        self.closed = False

    def close(self) -> None:
        self.active = False
        self.closed = True


class FakeBackend:
    def __init__(
        self,
        devices: list[AudioDevice] | None = None,
        defaults: dict[tuple[DeviceKind, str | None], int] | None = None,
    ) -> None:
        self._devices = laptop_devices() if devices is None else devices
        self.defaults = dict(LAPTOP_DEFAULTS if defaults is None else defaults)
        self.inputs: list[FakeStream] = []
        self.outputs: list[FakeStream] = []
        self.rescans = 0

    def devices(self) -> list[AudioDevice]:
        return list(self._devices)

    def default_device(self, kind: DeviceKind, host_api: str | None) -> AudioDevice | None:
        index = self.defaults.get((kind, host_api))
        return next((d for d in self._devices if d.index == index), None)

    def open_input(
        self, device: AudioDevice, sample_rate: int, block_frames: int, callback: InputCallback
    ) -> FakeStream:
        self._require_present(device)
        stream = FakeStream(device, sample_rate, block_frames, callback)
        self.inputs.append(stream)
        return stream

    def open_output(
        self, device: AudioDevice, sample_rate: int, block_frames: int, callback: OutputCallback
    ) -> FakeStream:
        self._require_present(device)
        stream = FakeStream(device, sample_rate, block_frames, callback)
        self.outputs.append(stream)
        return stream

    def rescan(self) -> None:
        self.rescans += 1

    # ------------------------------------------------------------ test controls

    def unplug(self, name_part: str) -> None:
        self._devices = [d for d in self._devices if name_part not in d.name]

    def replug(self, *devices: AudioDevice) -> None:
        self._devices.extend(devices)

    def _require_present(self, wanted: AudioDevice) -> None:
        if wanted not in self._devices:
            raise AudioDeviceError(f"{wanted.describe()} is gone")


class FakeClock:
    def __init__(self, start_ns: int = 1_000_000_000) -> None:
        self.now_ns = start_ns

    def __call__(self) -> int:
        return self.now_ns

    def advance_ms(self, ms: float) -> None:
        self.now_ns += int(ms * 1_000_000)


def audio_settings(**overrides: Any) -> AudioSettings:
    base: dict[str, Any] = {
        "host_api": WASAPI,
        "pipeline_sample_rate": 16_000,
        "frame_ms": 20,
        "resample_quality": "LQ",
        "reconnect_interval_ms": 10,
        "stall_timeout_ms": 1_000,
        "gil_switch_interval_ms": 1,
        "input": {"device": None, "sample_rate": None, "block_ms": 10, "buffer_ms": 2_000},
        "output": {"device": None, "sample_rate": None, "block_ms": 10, "buffer_ms": 2_000},
    }
    return AudioSettings.model_validate(deep_merge(base, overrides))


async def eventually(predicate: Callable[[], bool], timeout_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.005)

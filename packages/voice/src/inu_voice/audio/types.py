"""Audio domain types and the backend interface.

The engine talks to hardware only through `AudioBackend`, so everything above it
(ring buffers, resampling, reconnects) is tested against a fake backend. Backends
hand INU mono float32 audio and take mono float32 audio back; channel layouts stay
inside the backend.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import numpy as np
import numpy.typing as npt

from inu.errors import ErrorCategory, InuError

type Samples = npt.NDArray[np.float32]

# Called on the real-time audio thread. Must not block, log, or raise.
type InputCallback = Callable[[Samples, bool], None]  # (block, device reported overflow)
type OutputCallback = Callable[[Samples, bool], None]  # (block to fill, device underflow)


class DeviceKind(StrEnum):
    INPUT = "input"
    OUTPUT = "output"


class AudioDeviceError(InuError):
    code = "audio.device_unavailable"
    category = ErrorCategory.DEVICE
    retryable = True


@dataclass(frozen=True, slots=True)
class AudioDevice:
    index: int
    name: str
    host_api: str
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: int

    def supports(self, kind: DeviceKind) -> bool:
        channels = self.max_input_channels if kind is DeviceKind.INPUT else self.max_output_channels
        return channels > 0

    def describe(self) -> str:
        return f"{self.name} [{self.host_api}]"


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """A fixed-length block of mono audio at the pipeline sample rate."""

    samples: Samples
    sample_rate: int
    captured_at_ns: int  # perf_counter_ns when the frame's last sample was captured


class StreamHandle(Protocol):
    @property
    def active(self) -> bool: ...

    def close(self) -> None: ...


class AudioBackend(Protocol):
    def devices(self) -> list[AudioDevice]: ...

    def default_device(self, kind: DeviceKind, host_api: str | None) -> AudioDevice | None: ...

    def open_input(
        self, device: AudioDevice, sample_rate: int, block_frames: int, callback: InputCallback
    ) -> StreamHandle:
        """Open and start a capture stream."""
        ...

    def open_output(
        self, device: AudioDevice, sample_rate: int, block_frames: int, callback: OutputCallback
    ) -> StreamHandle:
        """Open and start a playback stream."""
        ...

    def rescan(self) -> None:
        """Refresh the device list. Only called while no stream is open."""
        ...

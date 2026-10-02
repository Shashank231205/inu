"""PortAudio backend, through the `sounddevice` package.

Excluded from unit-test coverage: it needs real audio hardware. It's exercised by the
hardware test and by `inu audio bench`.
"""

from types import ModuleType
from typing import Any

import numpy as np

from inu_voice.audio.types import (
    AudioDevice,
    AudioDeviceError,
    DeviceKind,
    InputCallback,
    OutputCallback,
    Samples,
)

MAX_CHANNELS = 2


class SoundDeviceBackend:
    def __init__(self) -> None:
        # Imported here: loading sounddevice needs the PortAudio library, which only
        # machines that run the voice loop have.
        import sounddevice

        self._sd: ModuleType = sounddevice

    def devices(self) -> list[AudioDevice]:
        apis = self._sd.query_hostapis()
        return [
            AudioDevice(
                index=index,
                name=info["name"],
                host_api=apis[info["hostapi"]]["name"],
                max_input_channels=info["max_input_channels"],
                max_output_channels=info["max_output_channels"],
                default_sample_rate=int(info["default_samplerate"]),
            )
            for index, info in enumerate(self._sd.query_devices())
        ]

    def default_device(self, kind: DeviceKind, host_api: str | None) -> AudioDevice | None:
        position = 0 if kind is DeviceKind.INPUT else 1
        if host_api is None:
            index = self._sd.default.device[position]
        else:
            api = next((a for a in self._sd.query_hostapis() if a["name"] == host_api), None)
            if api is None:
                return None
            index = api["default_input_device" if position == 0 else "default_output_device"]
        if index is None or int(index) < 0:
            return None
        return self.devices()[int(index)]

    def open_input(
        self, device: AudioDevice, sample_rate: int, block_frames: int, callback: InputCallback
    ) -> "_Stream":
        channels = min(device.max_input_channels, MAX_CHANNELS)

        def on_block(indata: Samples, frames: int, time_info: Any, status: Any) -> None:
            mono = indata[:, 0] if channels == 1 else indata.mean(axis=1, dtype=np.float32)
            callback(mono, bool(status.input_overflow))

        return self._start(
            self._sd.InputStream, device, sample_rate, block_frames, channels, on_block
        )

    def open_output(
        self, device: AudioDevice, sample_rate: int, block_frames: int, callback: OutputCallback
    ) -> "_Stream":
        channels = min(device.max_output_channels, MAX_CHANNELS)
        scratch = np.zeros(block_frames, dtype=np.float32)

        def on_block(outdata: Samples, frames: int, time_info: Any, status: Any) -> None:
            mono = scratch[:frames] if frames <= len(scratch) else np.zeros(frames, np.float32)
            callback(mono, bool(status.output_underflow))
            outdata[:] = mono[:, None]

        return self._start(
            self._sd.OutputStream, device, sample_rate, block_frames, channels, on_block
        )

    def rescan(self) -> None:
        # PortAudio only enumerates devices at initialisation.
        self._sd._terminate()
        self._sd._initialize()

    def _start(
        self,
        stream_class: Any,
        device: AudioDevice,
        sample_rate: int,
        block_frames: int,
        channels: int,
        on_block: Any,
    ) -> "_Stream":
        try:
            stream = stream_class(
                device=device.index,
                samplerate=sample_rate,
                blocksize=block_frames,
                channels=channels,
                dtype="float32",
                latency="low",
                callback=on_block,
            )
            stream.start()
        except self._sd.PortAudioError as exc:
            raise AudioDeviceError(
                f"Could not open {device.describe()} at {sample_rate} Hz: {exc}"
            ) from exc
        return _Stream(stream)


class _Stream:
    def __init__(self, stream: Any) -> None:
        self._stream = stream

    @property
    def active(self) -> bool:
        return bool(self._stream.active)

    def close(self) -> None:
        self._stream.close(ignore_errors=True)

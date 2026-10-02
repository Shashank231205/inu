"""Audio I/O. See docs/audio.md."""

from inu_voice.audio.capture import Microphone
from inu_voice.audio.devices import select_device
from inu_voice.audio.engine import AudioEngine
from inu_voice.audio.playback import Speaker
from inu_voice.audio.ring import RingBuffer
from inu_voice.audio.stats import AudioStats
from inu_voice.audio.types import (
    AudioBackend,
    AudioDevice,
    AudioDeviceError,
    AudioFrame,
    DeviceKind,
    StreamHandle,
)

__all__ = [
    "AudioBackend",
    "AudioDevice",
    "AudioDeviceError",
    "AudioEngine",
    "AudioFrame",
    "AudioStats",
    "DeviceKind",
    "Microphone",
    "RingBuffer",
    "Speaker",
    "StreamHandle",
    "select_device",
]

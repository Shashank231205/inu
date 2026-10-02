"""Per-direction counters, written only by the audio thread."""

from dataclasses import dataclass


@dataclass(slots=True)
class AudioStats:
    callbacks: int = 0
    samples: int = 0  # at the device rate; compared with wall time, reveals silent drops
    xruns: int = 0  # INU-side: capture ring full, or playback ran dry mid-utterance
    device_xruns: int = 0  # reported by the audio driver
    last_callback_ns: int = 0

"""Single-producer, single-consumer ring buffer for float32 samples.

One side runs on PortAudio's real-time thread, the other on the asyncio thread. The
real-time side must never wait on a lock the other side holds, so there is no lock:

* The producer is the only writer of `_written` and the consumer the only writer of
  `_read`. Both are monotonically increasing sample counts. The fill level is their
  difference, so neither side ever needs the other's cooperation to make progress.
* Samples are copied before the count that publishes them is advanced, so the
  other side never sees a slot it may not touch yet.
* Discarding everything (barge-in) is a *request* from the producer. The consumer
  carries it out, so `_read` keeps a single writer.

Under CPython's GIL, rebinding an attribute is atomic, which is what makes this safe.
"""

import numpy as np

from inu_voice.audio.types import Samples


class RingBuffer:
    __slots__ = ("_capacity", "_data", "_discard_to", "_read", "_written")

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._capacity = capacity
        self._data: Samples = np.zeros(capacity, dtype=np.float32)
        self._written = 0
        self._read = 0
        self._discard_to = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def written(self) -> int:
        """Total samples ever written."""
        return self._written

    def available(self) -> int:
        return self._written - self._read

    def free(self) -> int:
        return self._capacity - self.available()

    # ------------------------------------------------------------------ producer

    def write(self, samples: Samples) -> int:
        """Copy in as many samples as fit. Returns how many were written."""
        count = min(len(samples), self.free())
        if count:
            start = self._written % self._capacity
            first = min(count, self._capacity - start)
            self._data[start : start + first] = samples[:first]
            self._data[: count - first] = samples[first:count]
            self._written += count
        return count

    def request_discard(self) -> None:
        """Ask the consumer to drop everything written so far."""
        self._discard_to = self._written

    # ------------------------------------------------------------------ consumer

    def read_into(self, out: Samples) -> int:
        """Fill `out` from the front of the buffer. Returns how many samples were read."""
        self._apply_discard()
        count = min(len(out), self.available())
        if count:
            start = self._read % self._capacity
            first = min(count, self._capacity - start)
            out[:first] = self._data[start : start + first]
            out[first:count] = self._data[: count - first]
            self._read += count
        return count

    def read(self) -> Samples:
        """Take everything available as a new array."""
        self._apply_discard()
        out = np.empty(self.available(), dtype=np.float32)
        self.read_into(out)
        return out

    def _apply_discard(self) -> None:
        target = self._discard_to
        if target > self._read:
            self._read = target
